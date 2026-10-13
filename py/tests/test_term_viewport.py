"""Mirror "viewport" karesi (`viewport=1`, TBD#80 A) testleri: tek tmux süreci, yalnız görünür ekran (stdlib unittest).

Çalıştırma:  python3 -m unittest discover -s py/tests -p 'test_term_viewport.py' -v

Neden (TODO.md 2026-10-13, ölçüm): bir mirror yoklama tick'i oturum başına 3 tmux süreci (2000 satırlık
`capture-pane`, `list-panes`, `display-message`) ve 143 KB'lık metin üzerinde mod tespiti + lite dönüşümü çalıştırıyordu;
tick başına ~29 ms toplam CPU, tmux sunucusunda yalnız tam capture 12,7 ms. Mirror görüntüleyici yalnız görünür ekranı
çizer (`urls`/`paths`/`mode` okumaz), bu yüzden `viewport=1` ister ve tek süreçte yalnız görünür ekranı alır.

Gerçek tmux'a (testin kendi soketi) ve 127.0.0.1'e karşı koşar; canlı filoya DOKUNMAZ.
"""
import itertools
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import tmux_backend  # noqa: E402
from claudeops.commands import web, web_hosts, web_term_lite  # noqa: E402

_sockets = itertools.count()


class TmuxCase(unittest.TestCase):
    """Her test KENDİ tmux soketinde koşar (bir önceki testin `kill-server`ı bitmeden aynı sokette `new-session`
    açmak "server exited unexpectedly" ile düşüyordu)."""

    def setUp(self):
        self.sock = f"cops_test_viewport_{os.getpid()}_{next(_sockets)}"
        self.addCleanup(self.tmux, "kill-server")
        patcher = mock.patch.object(tmux_backend, "TMUX_SOCKET", self.sock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tmux(self, *args):
        return subprocess.run(["tmux", "-L", self.sock, *args], capture_output=True, text=True, timeout=10)

    def new_session(self, name, command="bash --norc --noprofile", rows=10):
        r = self.tmux("new-session", "-d", "-s", name, "-x", "80", "-y", str(rows), command)
        self.assertEqual(r.returncode, 0, r.stderr)

    def wait_for(self, name, needle, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if needle in self.tmux("capture-pane", "-t", name, "-p").stdout:
                return True
            time.sleep(0.05)
        self.fail(f"{needle!r} görünmedi")

    def fill_history(self, name="t"):
        """Renkli satırlar, scrollback'e kayan bir URL ve sonunda ekranda kalan bir işaret."""
        self.tmux("send-keys", "-t", name,
                  'echo "login https://e.test/device?code=ZZ9"; '
                  'for i in $(seq 1 40); do printf "hist %02d \\033[3%dmcolor\\033[0m\\n" $i $((i%7+1)); done; '
                  'echo DONE-$((6*7))', "Enter")
        self.wait_for(name, "DONE-42")


def tmux_spawns(fn):
    """`fn()`'in başlattığı tmux süreçlerinin argv listesi (süreç sayısı = uzunluk)."""
    real_run = subprocess.run
    seen = []

    def spy(argv, *a, **kw):
        if argv and argv[0] == "tmux":
            seen.append(list(argv))
        return real_run(argv, *a, **kw)

    with mock.patch.object(subprocess, "run", spy):
        result = fn()
    return result, seen


@unittest.skipUnless(shutil.which("tmux"), "tmux kurulu değil")
class SnapshotTests(TmuxCase):
    def setUp(self):
        super().setUp()
        self.new_session("t")
        self.fill_history("t")

    def test_returns_the_geometry_and_the_visible_screen(self):
        (cols, rows, hist, alt, tty), text = tmux_backend.tmux_pane_snapshot("t")
        self.assertEqual((cols, rows), (80, 10))
        self.assertGreater(hist, 20, "scrollback oluşmadı, test anlamsız")
        self.assertIs(alt, False)
        self.assertTrue(tty.startswith("/dev/"), tty)
        self.assertEqual(text.count("\n"), rows)                     # tam `rows` satır, her biri "\n" ile biter
        self.assertEqual(text, self.tmux("capture-pane", "-t", "t", "-e", "-p").stdout)
        self.assertIn("DONE-42", text)
        self.assertNotIn("hist 01", text)                            # scrollback'e kayan satırlar YOK

    def test_agrees_with_the_separate_calls_it_replaces(self):
        snap = tmux_backend.tmux_pane_snapshot("t")
        (cols, rows, hist, alt, _tty), text = snap
        self.assertEqual(tmux_backend.tmux_pane_size("t"), (cols, rows, hist, alt))
        full = tmux_backend.tmux_capture("t", 2000)
        self.assertEqual(web_term_lite.viewport_text(full, rows), text[:-1])
        self.assertEqual(tmux_backend.pane_is_masked_input("t"), tmux_backend.tty_is_masked(snap[0][4]))

    def test_it_is_one_tmux_process_running_two_commands(self):
        snap, spawns = tmux_spawns(lambda: tmux_backend.tmux_pane_snapshot("t"))
        self.assertIsNotNone(snap)
        self.assertEqual(len(spawns), 1, spawns)
        argv = spawns[0]
        self.assertIn(";", argv)                                     # yalın `;` elemanı: komut ayıracı
        self.assertEqual(argv[argv.index(";") - 1], tmux_backend._SNAPSHOT_FORMAT)

    def test_a_missing_session_is_none(self):
        self.assertIsNone(tmux_backend.tmux_pane_snapshot("yok"))

    def test_the_alternate_screen_is_reported(self):
        self.tmux("send-keys", "-t", "t", "printf '\\033[?1049h'; echo ALT-ON", "Enter")
        self.wait_for("t", "ALT-ON")
        (_c, _r, _h, alt, _t), text = tmux_backend.tmux_pane_snapshot("t")
        self.assertIs(alt, True)
        self.assertIn("ALT-ON", text)

    def test_a_gone_session_never_falls_back_to_a_longer_sibling_name(self):
        # 2026-09-17 olayı: çıplak ad hedefi tmux'ta ön ek eşleşmesi yapar, `ab` yokken `abc` yanıt verir ve mirror
        # YANLIŞ oturumun ekranını gösterirdi. `_exact` (`=ab:`) bunu keser.
        self.new_session("abc")
        self.assertIsNone(tmux_backend.tmux_pane_snapshot("ab"))
        self.assertIsNotNone(tmux_backend.tmux_pane_snapshot("abc"))

    def test_a_hostile_name_cannot_smuggle_a_tmux_command(self):
        # `_exact` hedefi `=ad:` yapar: `;` ortada ya da sonda olsa da tek argv elemanı, `:` ile biter, ayıraç olamaz.
        for hostile in ("x; kill-server", "x;", "x;kill-session -t t;"):
            self.assertIsNone(tmux_backend.tmux_pane_snapshot(hostile), hostile)
        self.assertEqual(self.tmux("has-session", "-t", "t").returncode, 0, "sunucu ya da oturum öldürüldü")

    def test_a_masked_prompt_is_visible_through_the_snapshot_pty(self):
        self.new_session("pw", "bash --norc --noprofile -c 'read -s -p \"password: \" x; sleep 30'")
        self.wait_for("pw", "password:")
        tty = tmux_backend.tmux_pane_snapshot("pw")[0][4]
        self.assertIs(tmux_backend.tty_is_masked(tty), True)
        self.assertIs(tmux_backend.pane_is_masked_input("pw"), True)  # eski yolla AYNI karar

    def test_tty_is_masked_is_none_without_a_usable_path(self):
        self.assertIsNone(tmux_backend.tty_is_masked(""))
        self.assertIsNone(tmux_backend.tty_is_masked("/dev/yok-boyle-bir-pty"))


class SnapshotParsingTests(unittest.TestCase):
    """tmux çıktısı beklenen biçimde değilse sessizce None (çağıran eski yola düşer)."""

    def snap(self, stdout, returncode=0):
        completed = SimpleNamespace(returncode=returncode, stdout=stdout)
        with mock.patch.object(tmux_backend.subprocess, "run", return_value=completed):
            return tmux_backend.tmux_pane_snapshot("t")

    def test_an_empty_pty_field_is_kept_as_an_empty_string(self):
        self.assertEqual(self.snap("80 24 123 1 \nbody\n"), ((80, 24, 123, True, ""), "body\n"))

    def test_malformed_output_is_none(self):
        for bad in ("", "no newline", "80 24 123\nbody\n", "a b c d /dev/pts/1\nbody\n", "80 24 1 0\nbody\n"):
            self.assertIsNone(self.snap(bad), bad)

    def test_a_failing_tmux_is_none(self):
        self.assertIsNone(self.snap("80 24 1 0 /dev/pts/1\nbody\n", returncode=1))

    def test_a_missing_tmux_binary_is_none(self):
        with mock.patch.object(tmux_backend.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(tmux_backend.tmux_pane_snapshot("t"))


@unittest.skipUnless(shutil.which("tmux"), "tmux kurulu değil")
class ViewportFrameTests(TmuxCase):
    def setUp(self):
        super().setUp()
        self.new_session("t")
        p = mock.patch.object(web, "_term_resolve",
                              lambda name, lang="tr": (SimpleNamespace(name=name, cli="shell"), None))
        p.start()
        self.addCleanup(p.stop)
        web._term_output_resolve_cache.clear()
        self.addCleanup(web._term_output_resolve_cache.clear)
        self.fill_history("t")

    def test_it_equals_the_classic_lite_frame_except_for_the_scrollback_derived_fields(self):
        classic = web_term_lite.to_lite(web._term_output("t", "en"))
        viewport = web._term_output("t", "en", viewport=True)
        for key in ("ok", "text", "cols", "rows", "history_size", "alternate_screen", "masked", "mode", "lite"):
            self.assertEqual(viewport[key], classic[key], key)
        self.assertEqual(set(viewport), set(classic))                # aynı alanlar, görüntüleyici farkı görmez
        self.assertTrue(viewport["lite"])
        self.assertEqual(viewport["text"].count("\n") + 1, viewport["rows"])   # sondaki newline yok, tam `rows` satır
        # Bilinçli fark: kayan giriş URL'si şeridi yalnız tam capture'dan çıkar, viewport karesi onu taşımaz.
        self.assertIn("https://e.test/device?code=ZZ9", classic["urls"])
        self.assertEqual((viewport["urls"], viewport["paths"]), ([], []))

    def test_the_first_line_is_self_contained_when_a_wrapped_colored_line_is_cut_at_the_top(self):
        # 150 karakterlik gri satır 80 + 70 olarak SARILIR; 2. yarı ekranın ilk satırı, 1. yarı scrollback'te kalır.
        # Tam capture'da 2. yarı için SGR basılmaz (renk 1. yarıdan devralınır), kırpınca renk kaybolur (eski lite
        # kare ilk satırı varsayılan renkte gösterirdi); görünür capture boş durumdan başlar ve rengi açıkça yazar.
        self.new_session("c", rows=10)
        self.tmux("send-keys", "-t", "c",
                  "clear; printf '\\033[38;5;246m'; printf 'x%.0s' $(seq 1 150); printf '\\033[0m\\n'; "
                  "for i in 1 2 3 4 5 6 7; do echo row$i; done; echo DONE-$((6*7))", "Enter")
        self.wait_for("c", "DONE-42")
        viewport = web._term_output("c", "en", viewport=True)
        classic = web_term_lite.to_lite(web._term_output("c", "en"))
        v_lines, c_lines = viewport["text"].split("\n"), classic["text"].split("\n")
        sgr = "\x1b[38;5;246m"
        self.assertTrue(v_lines[0].startswith(sgr), repr(v_lines[0][:30]))   # ilk satır kendi rengini kendisi taşır
        self.assertEqual(v_lines[1:], c_lines[1:])                           # ilk satır dışında birebir aynı
        self.assertEqual(v_lines[0].replace(sgr, "", 1), c_lines[0].replace(sgr, "", 1))   # önek dışında aynı içerik
        one_line = self.tmux("capture-pane", "-t", "c", "-e", "-p", "-S", "0", "-E", "0").stdout.rstrip("\n")
        self.assertEqual(v_lines[0], one_line)                               # temiz durumdan başlayan satırla aynı

    def test_the_frame_is_much_smaller_than_the_full_capture(self):
        full = web._term_output("t", "en")
        viewport = web._term_output("t", "en", viewport=True)
        self.assertGreater(len(full["text"]), 3 * len(viewport["text"]))

    def test_a_masked_prompt_is_reported(self):
        self.new_session("pw", "bash --norc --noprofile -c 'read -s -p \"password: \" x; sleep 30'")
        self.wait_for("pw", "password:")
        self.assertIs(web._term_output("pw", "en", viewport=True)["masked"], True)
        self.assertIs(web._term_output("pw", "en")["masked"], True)

    def test_the_classic_path_spawns_three_tmux_processes_and_the_viewport_path_one(self):
        _frame, classic = tmux_spawns(lambda: web._term_output("t", "en"))
        _frame, viewport = tmux_spawns(lambda: web._term_output("t", "en", viewport=True))
        self.assertEqual(len(classic), 3, classic)
        self.assertEqual(len(viewport), 1, viewport)

    def test_it_falls_back_to_the_classic_frame_when_the_single_call_fails(self):
        with mock.patch.object(web, "tmux_pane_snapshot", return_value=None):
            frame = web._term_output("t", "en", viewport=True)
        self.assertTrue(frame["ok"])
        self.assertNotIn("lite", frame)                              # sıradan tam kare: hız kaybı var, doğruluk kaybı yok
        self.assertEqual(frame["text"], web._term_output("t", "en")["text"])

    def test_a_gone_session_is_the_same_error_as_before_and_drops_the_resolve_cache(self):
        self.assertTrue(web._term_output("t", "en", viewport=True)["ok"])
        self.assertIn("t", web._term_output_resolve_cache)           # çözümleme önbelleğe girdi
        self.tmux("kill-session", "-t", "t")
        frame = web._term_output("t", "en", viewport=True)
        self.assertFalse(frame["ok"])
        self.assertEqual(frame, web._term_output("t", "en"))
        self.assertNotIn("t", web._term_output_resolve_cache)

    def test_the_mode_is_read_from_the_visible_screen(self):
        claude = SimpleNamespace(name="t", cli="claude")
        with mock.patch.object(web, "_term_resolve", lambda name, lang="tr": (claude, None)):
            web._term_output_resolve_cache.clear()
            self.assertIsNone(web._term_output("t", "en", viewport=True)["mode"])      # durum çubuğu yok
            self.tmux("send-keys", "-t", "t", "clear; echo 'plan mode on (shift+tab to cycle)'", "Enter")
            self.wait_for("t", "plan mode on")
            self.assertEqual(web._term_output("t", "en", viewport=True)["mode"], "plan")
            self.assertEqual(web._term_output("t", "en")["mode"], "plan")              # eski yolla AYNI karar


class PlumbingTests(unittest.TestCase):
    """`viewport` sorgu parametresinin yerel, REST ve röle dallarına doğru taşınması; False iken eski imza."""

    def frame(self, **extra):
        base = {"ok": True, "text": "v1\nv2\nv3", "cols": 80, "rows": 3, "history_size": 2,
                "alternate_screen": False, "masked": False, "mode": None, "lite": True, "urls": [], "paths": []}
        base.update(extra)
        return base

    def setUp(self):
        self.proxy_calls, self.relay_calls, self.output_calls = [], [], []
        self.tier = "rest"

        def fake_proxy_get(path, host, query):
            self.proxy_calls.append((path, host, dict(query)))
            return self.frame(), 200

        def fake_relay(host, name, lang, lite=False, **extra):
            self.relay_calls.append((host, name, lang, lite, extra))
            return lambda: self.frame()

        def fake_output(name, lang="tr", **extra):
            self.output_calls.append((name, lang, extra))
            return self.frame()

        for p in (mock.patch.object(web.web_hosts, "get_tier", lambda host: self.tier),
                  mock.patch.object(web.web_hosts, "proxy_get", fake_proxy_get),
                  mock.patch.object(web.web_hosts, "term_output_relay", fake_relay),
                  mock.patch.object(web, "_term_output", fake_output)):
            p.start()
            self.addCleanup(p.stop)

    def test_remote_query_adds_viewport_only_when_requested(self):
        self.assertEqual(web._term_remote_query("s1", "en", True), {"name": "s1", "lang": "en", "lite": "1"})
        self.assertEqual(web._term_remote_query("s1", "en", True, True),
                         {"name": "s1", "lang": "en", "lite": "1", "viewport": "1"})
        self.assertEqual(web._term_remote_query("s1", "en", False, False), {"name": "s1", "lang": "en"})

    def test_local_viewport_asks_the_viewport_frame_and_the_lite_wrapper_leaves_it_alone(self):
        out = web._term_fetch_fn(web.LOCAL_HOST_NAME, "s1", "en", True, viewport=True)()
        self.assertEqual(self.output_calls, [("s1", "en", {"viewport": True})])
        self.assertEqual(out, self.frame())

    def test_local_without_viewport_keeps_the_old_call_shape(self):
        web._term_fetch_fn(web.LOCAL_HOST_NAME, "s1", "en", True)()
        self.assertEqual(self.output_calls, [("s1", "en", {})])      # `viewport` anahtar sözcüğü HİÇ geçmez

    def test_rest_tier_forwards_viewport_to_the_remote_host(self):
        web._term_fetch_fn("yuhem", "s1", "en", True, viewport=True)()
        self.assertEqual(self.proxy_calls,
                         [("/api/term/output", "yuhem", {"name": "s1", "lang": "en", "lite": "1", "viewport": "1"})])

    def test_ws_tier_forwards_viewport_and_interval_to_the_relay(self):
        self.tier = "ws"
        web._term_fetch_fn("yuhem", "s1", "en", True, interval=1.0, viewport=True)()
        self.assertEqual(self.relay_calls, [("yuhem", "s1", "en", True, {"interval": 1.0, "viewport": True})])

    def test_ws_tier_without_viewport_keeps_the_old_call_shape(self):
        self.tier = "ws"
        web._term_fetch_fn("yuhem", "s1", "en", True, interval=1.0)()
        self.assertEqual(self.relay_calls, [("yuhem", "s1", "en", True, {"interval": 1.0})])


class RelayKeyTests(unittest.TestCase):
    """`web_hosts.term_output_relay`: viewport anahtara, URL'ye ve etikete girer; yoksa hepsi eskisi gibi."""

    def setUp(self):
        self.urls, self.labels = [], []

        class FakeRelay:
            def __init__(self_r, tier, make_call, parse_item, label=""):
                self_r.created_mono = time.monotonic()
                self_r.label = label
                labels = self.labels
                labels.append(label)

            def is_alive(self_r):
                return True

            def read(self_r):
                return {"ok": True}

            def stop(self_r):
                pass

        def fake_ws_url(base_url, path, token, **extra):
            self.urls.append(dict(extra))
            return "ws://x"

        host = {"base_url": "http://127.0.0.1:1", "token": "tok"}
        for p in (mock.patch.object(web_hosts, "_TermRelay", FakeRelay),
                  mock.patch.object(web_hosts, "_ws_url", fake_ws_url),
                  mock.patch.object(web_hosts, "get_tier", lambda name: "ws"),
                  mock.patch.object(web_hosts.hosts_mod, "get_host", lambda name: host)):
            p.start()
            self.addCleanup(p.stop)
        with web_hosts._term_relay_lock:
            web_hosts._term_relays.clear()
        self.addCleanup(lambda: web_hosts._term_relays.clear())

    def relay_keys(self):
        with web_hosts._term_relay_lock:
            return set(web_hosts._term_relays)

    def test_viewport_adds_the_query_parameter_the_label_and_the_key(self):
        web_hosts.term_output_relay("yuhem", "s1", "en", lite=True, interval=1.0, viewport=True)()
        self.assertEqual(self.urls, [{"name": "s1", "lang": "en", "lite": "1", "interval": "1", "viewport": "1"}])
        self.assertEqual(self.labels, ["term:yuhem/s1?lite@1s+viewport"])
        self.assertEqual(self.relay_keys(), {("yuhem", "s1", "en", True, 1.0, "viewport")})

    def test_without_viewport_url_label_and_key_are_exactly_as_before(self):
        web_hosts.term_output_relay("yuhem", "s1", "en", lite=True, interval=1.0)()
        web_hosts.term_output_relay("yuhem", "s1", "en", lite=True)()
        self.assertEqual(self.urls, [{"name": "s1", "lang": "en", "lite": "1", "interval": "1"},
                                     {"name": "s1", "lang": "en", "lite": "1"}])
        self.assertEqual(self.labels, ["term:yuhem/s1?lite@1s", "term:yuhem/s1?lite"])
        self.assertEqual(self.relay_keys(), {("yuhem", "s1", "en", True, 1.0), ("yuhem", "s1", "en", True)})

    def test_viewer_with_and_without_viewport_never_share_a_relay(self):
        web_hosts.term_output_relay("yuhem", "s1", "en", lite=True, interval=1.0, viewport=True)()
        web_hosts.term_output_relay("yuhem", "s1", "en", lite=True, interval=1.0)()
        self.assertEqual(len(self.relay_keys()), 2)


@unittest.skipUnless(shutil.which("tmux"), "tmux kurulu değil")
class RouteTests(TmuxCase):
    """Gerçek `_Handler` bir 127.0.0.1 sunucusunda: `/api/term/output` ve `/ws/term` sorgu çözümlemesi."""

    def setUp(self):
        super().setUp()
        self.new_session("t")
        for p in (mock.patch.object(web, "_term_resolve",
                                    lambda name, lang="tr": (SimpleNamespace(name=name, cli="shell"), None)),
                  mock.patch.object(web._Handler, "token", "tok")):
            p.start()
            self.addCleanup(p.stop)
        web._term_output_resolve_cache.clear()
        self.addCleanup(web._term_output_resolve_cache.clear)
        self.fill_history("t")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.port = self.server.server_address[1]

    def get(self, path_and_query):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path_and_query}",
                                     headers={"Authorization": "Bearer tok"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()

    def test_rest_viewport_returns_the_screen_only_frame(self):
        status, body = self.get("/api/term/output?name=t&lang=en&lite=1&viewport=1")
        frame = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(frame["lite"])
        self.assertEqual(frame["urls"], [])
        self.assertEqual(frame["text"].count("\n") + 1, frame["rows"])

    def test_rest_without_viewport_is_untouched(self):
        full = json.loads(self.get("/api/term/output?name=t&lang=en")[1])
        self.assertNotIn("lite", full)
        self.assertGreater(full["text"].count("\n"), full["rows"])    # scrollback dahil tam metin
        lite = json.loads(self.get("/api/term/output?name=t&lang=en&lite=1")[1])
        self.assertIn("https://e.test/device?code=ZZ9", lite["urls"])   # kayan URL şeridi eskisi gibi çalışır

    def test_ws_term_route_parses_viewport_and_passes_it_on(self):
        seen = {}

        def fake_fetch_fn(host, name, lang, lite, interval=None, viewport=False):
            seen.update(host=host, name=name, lang=lang, lite=lite, interval=interval, viewport=viewport)
            return lambda: {}

        def fake_handle(handler, fetch_fn, poll_seconds=None, name=None):
            seen["poll_seconds"] = poll_seconds
            handler.send_response(204)
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        with mock.patch.object(web, "_term_fetch_fn", fake_fetch_fn), \
                mock.patch.object(web.web_ws, "handle_ws_term", fake_handle):
            self.get("/ws/term?name=s1&host=yuhem&lang=en&lite=1&viewport=1&interval=1")
            with_viewport = dict(seen)
            seen.clear()
            self.get("/ws/term?name=s1&host=yuhem&lang=en&lite=1&interval=1")
        self.assertEqual(with_viewport["viewport"], True)
        self.assertEqual((with_viewport["lite"], with_viewport["interval"], with_viewport["name"]), (True, 1.0, "s1"))
        self.assertEqual(seen["viewport"], False)                    # parametre yoksa False


if __name__ == "__main__":
    unittest.main()

"""`GET /api/term/history` (web._term_history + rota) testleri: mirror'ın geçmişte kaydırması için küçük, aralıklı
scrollback ucu (TBD#79). Gerçek tmux'a (ayrı soket) ve 127.0.0.1'e karşı koşar; canlı filoya DOKUNMAZ.

Çalıştırma:  python3 -m unittest discover -s py/tests -p 'test_term_history.py' -v
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
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import tmux_backend  # noqa: E402
from claudeops.commands import web, web_hosts, web_term_lite  # noqa: E402

_sockets = itertools.count()


class TmuxCase(unittest.TestCase):
    """Her test KENDİ tmux soketinde koşar: bir önceki testin `kill-server`ı bitmeden aynı sokette `new-session`
    açmak "server exited unexpectedly" ile düşüyordu."""

    def setUp(self):
        self.sock = f"cops_test_term_hist_{os.getpid()}_{next(_sockets)}"
        self.addCleanup(self.tmux, "kill-server")
        patcher = mock.patch.object(tmux_backend, "TMUX_SOCKET", self.sock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tmux(self, *args):
        return subprocess.run(["tmux", "-L", self.sock, *args], capture_output=True, text=True, timeout=10)


@unittest.skipUnless(shutil.which("tmux"), "tmux kurulu değil")
class TermHistoryTests(TmuxCase):
    ROWS = 10

    def setUp(self):
        super().setUp()
        r = self.tmux("new-session", "-d", "-s", "t", "-x", "80", "-y", str(self.ROWS), "bash --norc --noprofile")
        self.assertEqual(r.returncode, 0, r.stderr)
        patcher = mock.patch.object(web, "_term_resolve", lambda name, lang="tr": (SimpleNamespace(name=name, cli="shell"), None))
        patcher.start()
        self.addCleanup(patcher.stop)
        web._term_output_resolve_cache.clear()
        self.addCleanup(web._term_output_resolve_cache.clear)
        self.tmux("send-keys", "-t", "t", 'for i in $(seq 1 120); do printf "L%03d \\033[3%dmcolor\\033[0m\\n" $i $((i%7+1)); done; echo DONE-$((6*7))', "Enter")
        self.wait_for("DONE-42")
        self.hist = tmux_backend.tmux_pane_size("t")[2]
        self.assertGreater(self.hist, 100, "scrollback oluşmadı, test anlamsız")

    def wait_for(self, needle, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if needle in self.tmux("capture-pane", "-t", "t", "-p").stdout:
                return True
            time.sleep(0.05)
        self.fail(f"{needle!r} görünmedi")

    def history(self, start, end):
        return web._term_history("t", start, end, "en")

    @staticmethod
    def numbers(text):
        out = []
        for line in text.split("\n"):
            plain = tmux_backend.strip_ansi(line)
            if plain.startswith("L") and plain[1:4].isdigit():
                out.append(int(plain[1:4]))
        return out

    def test_a_page_is_exactly_the_requested_lines_and_matches_tmux(self):
        r = self.history(-20, -11)
        self.assertTrue(r["ok"])
        self.assertEqual((r["start"], r["end"]), (-20, -11))
        self.assertEqual(r["text"].count("\n") + 1, 10)
        direct = self.tmux("capture-pane", "-t", "t", "-e", "-p", "-S", "-20", "-E", "-11").stdout
        self.assertEqual(r["text"], direct[:-1])

    def test_lines_are_in_order_and_just_above_the_screen(self):
        top = self.numbers(self.history(-self.hist, -1)["text"])
        self.assertEqual(top, sorted(top))
        self.assertEqual(top, list(range(top[0], top[0] + len(top))))
        visible = self.numbers(self.history(0, self.ROWS - 1)["text"])
        # geçmişin son numaralı satırı ile ekranın ilk numaralı satırı ardışık
        self.assertEqual(visible[0], top[-1] + 1)

    def test_pages_tile_the_whole_buffer_without_gaps_or_overlap(self):
        full = self.tmux("capture-pane", "-t", "t", "-e", "-p", "-S", "-2000").stdout
        lines, start = [], -self.hist
        while start <= self.ROWS - 1:
            r = self.history(start, start + 6)
            self.assertEqual(r["start"], start)
            lines.append(r["text"])
            start = r["end"] + 1
        self.assertEqual("\n".join(lines), full[:-1])

    def test_the_visible_range_equals_the_live_viewport(self):
        full = self.tmux("capture-pane", "-t", "t", "-e", "-p", "-S", "-2000").stdout
        self.assertEqual(self.history(0, self.ROWS - 1)["text"], web_term_lite.viewport_text(full, self.ROWS))

    def test_colours_are_kept(self):
        self.assertIn("\x1b[", self.history(-20, -11)["text"])

    def test_the_range_is_clamped_to_the_real_buffer(self):
        r = self.history(-10 ** 6, -self.hist + 2)
        self.assertEqual((r["start"], r["end"]), (-self.hist, -self.hist + 2))
        r = self.history(self.ROWS - 3, 10 ** 6)
        self.assertEqual((r["start"], r["end"]), (self.ROWS - 3, self.ROWS - 1))
        self.assertEqual(r["text"].count("\n") + 1, 3)

    def test_one_request_never_returns_more_than_the_cap(self):
        with mock.patch.object(web, "TERM_HISTORY_MAX_LINES", 4):
            r = self.history(-self.hist, self.ROWS - 1)
        self.assertEqual((r["start"], r["end"]), (-self.hist, -self.hist + 3))
        self.assertEqual(r["text"].count("\n") + 1, 4)

    def test_the_default_cap_is_far_below_a_full_capture(self):
        self.assertLessEqual(web.TERM_HISTORY_MAX_LINES, 500)

    def test_reversed_and_out_of_range_requests_are_errors(self):
        for start, end in ((5, 1), (self.ROWS + 5, self.ROWS + 9), (-self.hist - 50, -self.hist - 40)):
            r = self.history(start, end)
            self.assertFalse(r["ok"], (start, end))
            self.assertEqual(r["error"], "invalid line range")

    def test_the_reply_carries_what_the_client_needs_to_realign(self):
        r = self.history(-3, -1)
        self.assertEqual((r["history_size"], r["rows"], r["cols"], r["alternate_screen"]), (self.hist, self.ROWS, 80, False))

    def test_history_growth_shifts_the_numbering_and_the_reply_says_so(self):
        before = self.history(-1, -1)
        self.tmux("send-keys", "-t", "t", 'for i in $(seq 1 15); do echo MORE-$i; done; echo DONE-$((7*7))', "Enter")
        self.wait_for("DONE-49")
        after = self.history(-1, -1)
        self.assertGreater(after["history_size"], before["history_size"])
        self.assertNotEqual(after["text"], before["text"])

    def test_session_gone_is_a_clear_error_and_drops_the_resolve_cache(self):
        web._term_output_resolve_cache["t"] = (SimpleNamespace(name="t", cli="shell"), time.monotonic())
        self.tmux("kill-server")
        r = self.history(-5, -1)
        self.assertFalse(r["ok"])
        self.assertIn("no longer exists", r["error"])
        self.assertNotIn("t", web._term_output_resolve_cache)

    def test_a_failed_capture_after_a_good_size_query_drops_the_resolve_cache_too(self):
        web._term_output_resolve_cache["t"] = (SimpleNamespace(name="t", cli="shell"), time.monotonic())
        with mock.patch.object(web, "tmux_capture_range", lambda *a, **k: None):   # oturum iki çağrı arasında kapandı
            r = self.history(-5, -1)
        self.assertFalse(r["ok"])
        self.assertIn("no longer exists", r["error"])
        self.assertNotIn("t", web._term_output_resolve_cache)

    def test_a_full_screen_app_that_started_in_the_alternate_screen_has_no_history(self):
        r = self.tmux("new-session", "-d", "-s", "a", "-x", "60", "-y", "6",
                 r"printf '\033[?1049h'; echo ALT-$((8*8)); sleep 30")
        self.assertEqual(r.returncode, 0, r.stderr)
        end = time.monotonic() + 8
        while "ALT-64" not in self.tmux("capture-pane", "-t", "a", "-p").stdout and time.monotonic() < end:
            time.sleep(0.05)
        r = web._term_history("a", -50, 5, "en")
        self.assertTrue(r["ok"])
        self.assertTrue(r["alternate_screen"])
        self.assertEqual((r["history_size"], r["start"], r["end"]), (0, 0, 5))
        self.assertIn("ALT-64", r["text"])

    def test_the_reply_flags_the_alternate_screen_even_when_old_history_exists(self):
        self.tmux("send-keys", "-t", "t", r"printf '\033[?1049h'; echo ALT-$((9*9)); sleep 30", "Enter")
        self.wait_for("ALT-81")
        r = self.history(-5, self.ROWS - 1)
        self.assertTrue(r["ok"])
        self.assertTrue(r["alternate_screen"])
        self.tmux("send-keys", "-t", "t", "C-c")

    def test_range_values_cannot_reach_the_tmux_command_line(self):
        # tmux, `;` ile biten bir argümanı KOMUT AYIRACI sayar: "0;" geçerli bir capture + ardından yeni bir komut olurdu.
        # `int()` zorlaması bunu daha argv'ye girmeden keser (sayı olmayan değer → None, tmux hiç çağrılmaz).
        self.assertIsNone(tmux_backend.tmux_capture_range("t", "0;", 0))
        self.assertIsNone(tmux_backend.tmux_capture_range("t", -1, "0;"))
        self.assertIsNone(tmux_backend.tmux_capture_range("t", "-1; kill-server", 0))
        self.assertIsNotNone(tmux_backend.tmux_capture_range("t", -1, 0))     # kontrol: sayılar çalışır
        self.assertEqual(self.tmux("ls").returncode, 0)


@unittest.skipUnless(shutil.which("tmux"), "tmux kurulu değil")
class TermHistoryRouteTests(TmuxCase):
    """`do_GET` rotası: gerçek `_Handler` bir 127.0.0.1 sunucusunda."""

    def setUp(self):
        super().setUp()
        r = self.tmux("new-session", "-d", "-s", "t", "-x", "80", "-y", "6", "bash --norc --noprofile")
        self.assertEqual(r.returncode, 0, r.stderr)
        for p in (
                  mock.patch.object(web, "_term_resolve", lambda name, lang="tr": (SimpleNamespace(name=name, cli="shell"), None)),
                  mock.patch.object(web._Handler, "token", "tok")):
            p.start()
            self.addCleanup(p.stop)
        web._term_output_resolve_cache.clear()
        self.addCleanup(web._term_output_resolve_cache.clear)
        self.tmux("send-keys", "-t", "t", 'for i in $(seq 1 40); do echo R$i; done; echo DONE-$((6*7))', "Enter")
        end = time.monotonic() + 8
        while "DONE-42" not in self.tmux("capture-pane", "-t", "t", "-p").stdout and time.monotonic() < end:
            time.sleep(0.05)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.port = self.server.server_address[1]

    def get(self, query, token="tok"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/term/history?{query}",
                                     headers={"Authorization": f"Bearer {token}"} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            e.close()
            try:
                return e.code, json.loads(body or b"{}")
            except ValueError:   # 401 gövdesi JSON olmayabilir
                return e.code, {}

    def test_local_page(self):
        status, body = self.get("name=t&lang=en&start=-4&end=-1")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual((body["start"], body["end"]), (-4, -1))
        self.assertEqual(body["text"].count("\n") + 1, 4)

    def test_it_needs_the_token(self):
        self.assertEqual(self.get("name=t&start=-4&end=-1", token="yanlis")[0], 401)
        self.assertEqual(self.get("name=t&start=-4&end=-1", token=None)[0], 401)

    def test_name_and_integer_range_are_required(self):
        status, body = self.get("lang=en&start=-4&end=-1")
        self.assertEqual((status, body["error"]), (400, "name is required"))
        for query in ("name=t&lang=en&start=a&end=-1", "name=t&lang=en&start=-4", "name=t&lang=en&end=-1",
                      "name=t&lang=en&start=-4&end=1.5"):
            status, body = self.get(query)
            self.assertEqual((status, body["error"]), (400, "invalid line range"), query)

    def test_a_remote_host_is_proxied_with_a_clean_query(self):
        calls = []

        def fake_proxy(path, host, query, dedup=True):
            calls.append((path, host, dict(query), dedup))
            return {"ok": True, "text": "uzak", "start": -4, "end": -1}, 200

        with mock.patch.object(web_hosts, "proxy_get", fake_proxy):
            status, body = self.get("name=t&lang=en&host=yuhem&start=-4&end=-1")
        self.assertEqual((status, body["text"]), (200, "uzak"))
        # dedup=False: her sayfa ayrı URL, `_dedup_last_good` sayfa başına bir kayıtla sınırsız şişerdi
        self.assertEqual(calls, [("/api/term/history", "yuhem", {"name": "t", "lang": "en", "start": "-4", "end": "-1"}, False)])

    def test_a_remote_error_status_reaches_the_client(self):
        with mock.patch.object(web_hosts, "proxy_get", lambda path, host, query, dedup=True: ({"error": "not found"}, 404)):
            status, body = self.get("name=t&lang=en&host=eski&start=-4&end=-1")
        self.assertEqual((status, body), (404, {"error": "not found"}))

    def test_the_path_is_listed_as_host_routed(self):
        self.assertIn("/api/term/history", web_hosts.GET_HOST_ROUTED_PATHS)


class ProxyGetDedupTests(unittest.TestCase):
    """`web_hosts.proxy_get(dedup=...)`: sayfa başına benzersiz URL'li istekler `_dedup_last_good`'u şişirmesin."""

    def setUp(self):
        from http.server import BaseHTTPRequestHandler

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                data = json.dumps({"ok": True, "text": "x" * 100, "path": self.path}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        host = {"name": "h", "base_url": f"http://127.0.0.1:{self.server.server_address[1]}", "token": "t"}
        patcher = mock.patch.object(web_hosts.hosts_mod, "get_host", lambda name: host)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.before = set(web_hosts._dedup_last_good)
        self.addCleanup(lambda: [web_hosts._dedup_last_good.pop(k, None) for k in set(web_hosts._dedup_last_good) - self.before])

    def added(self):
        return set(web_hosts._dedup_last_good) - self.before

    def test_dedup_defaults_to_on_and_keeps_one_entry_per_url(self):
        web_hosts.proxy_get("/api/term/output", "h", {"name": "a"})
        web_hosts.proxy_get("/api/term/output", "h", {"name": "a"})
        self.assertEqual(len(self.added()), 1)

    def test_a_page_request_without_dedup_leaves_no_trace(self):
        for start in range(-300, 0, 10):                     # sayfa sayfa gezen bir kullanıcı
            body, status = web_hosts.proxy_get("/api/term/history", "h",
                                               {"name": "a", "start": str(start), "end": str(start + 9)}, dedup=False)
            self.assertEqual((status, body["ok"]), (200, True))
        self.assertEqual(self.added(), set())
        self.assertEqual(web_hosts._inflight_starts, {})

    def test_without_dedup_overlapping_identical_requests_are_not_turned_away(self):
        url_query = {"name": "a", "start": "-5", "end": "-1"}
        results = []
        threads = [threading.Thread(target=lambda: results.append(
            web_hosts.proxy_get("/api/term/history", "h", url_query, dedup=False)[0]["ok"])) for _ in range(4)]
        [t.start() for t in threads]
        [t.join(10) for t in threads]
        self.assertEqual(results, [True] * 4)               # "busy" yok


if __name__ == "__main__":
    unittest.main()


class DedupLastGoodBoundTests(unittest.TestCase):
    def test_cache_is_lru_bounded(self):
        before = dict(web_hosts._dedup_last_good)
        self.addCleanup(lambda: (web_hosts._dedup_last_good.clear(), web_hosts._dedup_last_good.update(before)))
        web_hosts._dedup_last_good.clear()
        cap = web_hosts._DEDUP_LAST_GOOD_MAX
        for i in range(cap + 50):
            web_hosts._remember_good(f"http://h/api/files/read?path=/{i}", 200, {"i": i})
        self.assertEqual(len(web_hosts._dedup_last_good), cap)
        self.assertNotIn("http://h/api/files/read?path=/0", web_hosts._dedup_last_good)            # en eski atıldı
        self.assertIn(f"http://h/api/files/read?path=/{cap + 49}", web_hosts._dedup_last_good)
        web_hosts._remember_good("http://h/api/files/read?path=/60", 200, {"i": "yeni"})            # yeniden kullanılan korunur
        for i in range(cap):
            web_hosts._remember_good(f"http://h/x/{i}", 200, {})
        self.assertNotIn("http://h/api/files/read?path=/60", web_hosts._dedup_last_good)

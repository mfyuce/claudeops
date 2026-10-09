"""`web_term_lite` + `web_ws._term_poll_loop` anahtarı için testler (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_web_term_lite.py -v

Ağa DOKUNMAZ. `RealTmuxCaptureTests` yalnız tmux kuruluysa koşar ve CANLI `cops` soketine
değil, bu sürece özel adlı AYRI bir tmux sunucusuna konuşur (`kill-server` yalnız onu kapatır).

Kapsadığı tasarım (TODO.md 2026-10-08 "Terminal karesi çok büyük"): her kare tam
`capture-pane -S -2000` yerine yalnız görünür satırları taşır; URL/yol şeridi tam metinden
sunucuda çıkarılır.
"""
import copy
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_term_lite, web_ws  # noqa: E402


def frame(text, rows=3, **extra):
    """`_term_output`-şekilli ok:true kare."""
    base = {"ok": True, "text": text, "cols": 80, "rows": rows, "history_size": 0,
            "alternate_screen": False, "masked": False, "mode": None}
    base.update(extra)
    return base


class ViewportTests(unittest.TestCase):
    def test_keeps_last_rows_and_drops_trailing_newline(self):
        full = "h1\nh2\nh3\nv1\nv2\nv3\n"
        lite = web_term_lite.to_lite(frame(full, rows=3, history_size=3))
        self.assertEqual(lite["text"], "v1\nv2\nv3")
        self.assertTrue(lite["lite"])

    def test_no_scrollback_returns_everything(self):
        lite = web_term_lite.to_lite(frame("a\nb\n", rows=5))
        self.assertEqual(lite["text"], "a\nb")

    def test_blank_bottom_rows_are_kept(self):
        # Görünür ekranın alt satırları boşsa onlar da `rows`'a sayılır; kırpma boşluğa bakmaz.
        lite = web_term_lite.to_lite(frame("old\nv1\n\n\n", rows=3))
        self.assertEqual(lite["text"], "v1\n\n")

    def test_without_trailing_newline(self):
        self.assertEqual(web_term_lite.viewport_text("a\nb\nc", 2), "b\nc")

    def test_input_is_not_mutated(self):
        original = frame("h\nv1\nv2\n", rows=2)
        snapshot = copy.deepcopy(original)
        web_term_lite.to_lite(original)
        self.assertEqual(original, snapshot)

    def test_other_fields_pass_through(self):
        lite = web_term_lite.to_lite(frame("h\nv\n", rows=1, history_size=1, masked=True, mode="plan",
                                           alternate_screen=False))
        for key, want in (("cols", 80), ("rows", 1), ("history_size", 1), ("masked", True),
                          ("mode", "plan"), ("alternate_screen", False), ("ok", True)):
            self.assertEqual(lite[key], want, key)

    def test_not_ok_and_unknown_rows_are_returned_as_is(self):
        err = {"ok": False, "error": "gone"}
        self.assertIs(web_term_lite.to_lite(err), err)
        no_rows = frame("a\nb\n", rows=None)
        self.assertIs(web_term_lite.to_lite(no_rows), no_rows)
        zero = frame("a\n", rows=0)
        self.assertIs(web_term_lite.to_lite(zero), zero)
        self.assertIsNone(web_term_lite.to_lite(None))
        self.assertNotIn("lite", no_rows)

    def test_bool_rows_is_not_accepted(self):
        weird = frame("a\nb\n", rows=True)
        self.assertIs(web_term_lite.to_lite(weird), weird)


class ExtractionTests(unittest.TestCase):
    """`UrlBanner.tsx`'in extractTermUrls / extractTermPathCandidates davranışıyla AYNI olmalı."""

    def test_newest_first_deduped_and_capped_at_three(self):
        text = "\n".join(f"see https://e.test/{n} now" for n in (1, 2, 3, 4)) + "\nagain https://e.test/4 \n"
        self.assertEqual(web_term_lite.extract_urls(text),
                         ["https://e.test/4", "https://e.test/3", "https://e.test/2"])

    def test_trailing_punctuation_is_trimmed(self):
        self.assertEqual(web_term_lite.extract_urls("open (https://e.test/x). then https://e.test/y,"),
                         ["https://e.test/y", "https://e.test/x"])

    def test_ansi_inside_url_is_stripped_before_matching(self):
        text = "go \x1b[4mhttps://e.test/\x1b[0mlogin?code=AB12 done"
        self.assertEqual(web_term_lite.extract_urls(text), ["https://e.test/login?code=AB12"])

    def test_path_candidates_cap_min_length_and_prefixes(self):
        text = "a / b ~/notes.md ./rel/file.txt ../up/x.py /abs/path.pdf"
        self.assertEqual(web_term_lite.extract_path_candidates(text),
                         ["/abs/path.pdf", "../up/x.py", "./rel/file.txt", "~/notes.md"])
        many = " ".join(f"/p/{n}.txt" for n in range(20))
        got = web_term_lite.extract_path_candidates(many)
        self.assertEqual(len(got), web_term_lite.MAX_PATH_CANDIDATES)
        self.assertEqual(got[0], "/p/19.txt")

    def test_url_in_scrollback_survives_the_viewport_cut(self):
        full = "login: https://e.test/device?c=XYZ\nfiller\nv1\nv2\n"
        lite = web_term_lite.to_lite(frame(full, rows=2, history_size=2))
        self.assertEqual(lite["text"], "v1\nv2")
        self.assertEqual(lite["urls"], ["https://e.test/device?c=XYZ"])
        self.assertNotIn("e.test", lite["text"])

    def test_memo_skips_rescan_for_identical_text(self):
        memo = {}
        with mock.patch.object(web_term_lite, "_scan_lines", wraps=web_term_lite._scan_lines) as scan:
            web_term_lite.to_lite(frame("https://a.test\nv\n", rows=1), memo)
            web_term_lite.to_lite(frame("https://a.test\nv\n", rows=1), memo)
            self.assertEqual(scan.call_count, 1)
            web_term_lite.to_lite(frame("https://b.test\nv\n", rows=1), memo)
            self.assertEqual(scan.call_count, 2)

    def test_changed_text_scans_only_new_lines(self):
        memo = {}
        base = [f"line {i} https://e.test/{i} /srv/f{i}.txt" for i in range(50)]
        web_term_lite.to_lite(frame("\n".join(base) + "\n", rows=5), memo)
        # Bir sonraki tick: en eski satır scrollback'ten düştü, altta iki YENİ satır var.
        nxt = base[1:] + ["fresh one /srv/new1.txt", "fresh two https://e.test/new2"]
        with mock.patch.object(web_term_lite, "strip_ansi", wraps=web_term_lite.strip_ansi) as sa:
            web_term_lite.to_lite(frame("\n".join(nxt) + "\n", rows=5), memo)
        # 52 satır (sondaki "" dahil 53 parça) var ama yalnız 2 yeni; "" bir önceki taramada görülmüştü.
        self.assertEqual(sa.call_count, 2)

    def test_line_cache_matches_whole_text_reference(self):
        """Satır önbelleği, tam metni tek seferde tarayan referansla HER tick'te aynı sonucu vermeli
        (kayan pencere, tekrar eden satırlar, ANSI, URL'siz/yolsuz satırlar, ortada değişen satır)."""
        import random
        rng = random.Random(7)
        pool = ["plain words only", "", "see https://e.test/%d now", "\x1b[1mopen ./rel/%d.txt\x1b[0m",
                "cfg at ~/conf/%d.yaml and /etc/%d.conf", "go \x1b[4mhttps://e.test/\x1b[0mpath%d done.",
                "dup line https://e.test/dup", "/p/%d,", "(https://e.test/x%d)."]
        def fill(p):
            return p.replace("%d", str(rng.randrange(1000)))

        window = [fill(rng.choice(pool)) for _ in range(300)]
        memo = {}
        for tick in range(40):
            for _ in range(rng.randrange(1, 6)):          # alta yeni satırlar, üstten düşenler
                window.append(fill(rng.choice(pool)))
                window.pop(0)
            if tick % 7 == 3:                              # ortada bir satır da değişsin
                window[rng.randrange(len(window))] = "mid /changed/%d.log" % tick
            text = "\n".join(window) + "\n"
            lite = web_term_lite.to_lite(frame(text, rows=20), memo)
            self.assertEqual(lite["urls"], web_term_lite.extract_urls(text), f"tick {tick}")
            self.assertEqual(lite["paths"], web_term_lite.extract_path_candidates(text), f"tick {tick}")
            # önbellek yalnız son metindeki benzersiz satırlar kadar: sınırsız büyümez
            self.assertLessEqual(len(memo["lines"]), len(set(text.split("\n"))))

    def test_path_regex_equals_ui_banner_pattern(self):
        """`_PATH_RE` hız için yeniden yazıldı; dil UrlBanner.tsx'in TERM_PATH_RE'siyle AYNI kalmalı
        (aynı `findall` sonucu, yalnız 'aynı kümeyi kabul eder' değil)."""
        import random
        import re
        ui_pattern = re.compile(r"(?:~|\.{1,2})?/[^\s<>\"'\x1b\x07]+")
        edge = ["", "/", "//", "~/", "./", "../", ".../c", "...//x", "~~/x", "a./b", "a../b", "x/y", ". /a",
                "~ /a", "..", "a b/c d/e", "end./", "(/a/b).", "\x1b[1m/a\x1b[0m/b", "<a>/b</a>",
                "'/q' \"/r\"", "~/a~/b ./c ../d /e"]
        rng = random.Random(11)
        alphabet = list("/./.~~ab \n<>\"'\x1b\x07") + ["..", "../", "./", "~/", "http://x/y", "\t"]
        cases = edge + ["".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40))) for _ in range(5000)]
        for case in cases:
            self.assertEqual(web_term_lite._PATH_RE.findall(case), ui_pattern.findall(case), repr(case))

    def test_memo_less_call_matches_memoized_call(self):
        text = "a https://e.test/1 /x/y.txt\nb ./z.md\nv1\nv2\n"
        cold = web_term_lite.to_lite(frame(text, rows=2))
        warm = web_term_lite.to_lite(frame(text, rows=2), {})
        self.assertEqual((cold["urls"], cold["paths"]), (warm["urls"], warm["paths"]))

    def test_already_lite_frame_is_returned_as_is(self):
        once = web_term_lite.to_lite(frame("https://e.test/old\nh\nv1\nv2\n", rows=2))
        self.assertEqual(once["urls"], ["https://e.test/old"])
        twice = web_term_lite.to_lite(once)
        self.assertIs(twice, once)
        self.assertEqual(twice["urls"], ["https://e.test/old"])


class PollLoopKeyTests(unittest.TestCase):
    """Anahtar genişledi: ekranı aynı kalan ama URL/history'si değişen kare yutulmamalı;
    hiçbir şeyi değişmeyen kare ise yollanmamalı (bandwidth kazancının kendisi)."""

    def run_loop(self, frames):
        sent = []
        client = SimpleNamespace(closed=threading.Event())
        script = iter(frames)

        def fetch():
            try:
                return next(script)
            except StopIteration:
                client.closed.set()
                return None

        def fake_send(_client, data):
            sent.append(data)
            return True

        with mock.patch.object(web_ws, "_send", fake_send), mock.patch.object(web_ws, "_TERM_POLL_SECONDS", 0.0):
            t = threading.Thread(target=web_ws._term_poll_loop, args=(client, fetch), daemon=True)
            t.start()
            t.join(5)
            self.assertFalse(t.is_alive(), "poll döngüsü bitmedi")
        return sent

    def test_identical_frames_are_sent_once(self):
        a = web_term_lite.to_lite(frame("h\nv\n", rows=1, history_size=1))
        sent = self.run_loop([a, dict(a), dict(a)])
        self.assertEqual(len(sent), 1)

    def test_changes_in_side_fields_alone_are_sent(self):
        a = web_term_lite.to_lite(frame("h\nv\n", rows=1, history_size=1))
        variants = [dict(a, urls=["https://x.test"]), dict(a, history_size=2),
                    dict(a, masked=True), dict(a, mode="plan"), dict(a, paths=["/tmp/x"])]
        sent = self.run_loop([a, dict(a)] + variants)
        self.assertEqual(len(sent), 1 + len(variants))

    def test_viewport_text_change_is_sent(self):
        a = web_term_lite.to_lite(frame("h\nv1\n", rows=1))
        b = web_term_lite.to_lite(frame("h\nv2\n", rows=1))
        self.assertEqual(len(self.run_loop([a, b])), 2)

    def test_route_wrapper_with_memo_sends_only_real_changes(self):
        """`web.py`'nin `/ws/term?lite=1` sarmalayıcısının AYNISI (bağlantıya özel memo ile `to_lite`):
        scrollback'e düşen satır ekranı değiştirmediği sürece (aynı görünür satırlar, aynı history_size)
        kare yollanmaz; ekranda ya da URL listesinde değişiklik varsa yollanır; URL ekrandan kaysa da
        listede kalır."""
        def fulltext(history, visible):
            return "".join(l + "\n" for l in history + visible)

        base_hist = [f"h{i}" for i in range(5)]
        shots = [
            frame(fulltext(["https://e.test/login"] + base_hist, ["v1", "v2"]), rows=2, history_size=6),
            frame(fulltext(["https://e.test/login"] + base_hist, ["v1", "v2"]), rows=2, history_size=6),  # aynı
            frame(fulltext(["https://e.test/login"] + base_hist, ["v1", "v3"]), rows=2, history_size=6),  # ekran değişti
            frame(fulltext(["https://e.test/login"] + base_hist + ["v1"], ["v3", "v4"]), rows=2, history_size=7),
        ]
        wrapped = (lambda inner, memo: lambda: web_term_lite.to_lite(inner(), memo))(
            lambda it=iter(shots): next(it), {})
        client = SimpleNamespace(closed=threading.Event())
        sent = []

        def fetch():
            try:
                return wrapped()
            except StopIteration:
                client.closed.set()
                return None

        import json
        with mock.patch.object(web_ws, "_send", lambda _c, data: sent.append(json.loads(data)) or True), \
                mock.patch.object(web_ws, "_TERM_POLL_SECONDS", 0.0):
            t = threading.Thread(target=web_ws._term_poll_loop, args=(client, fetch), daemon=True)
            t.start()
            t.join(5)
            self.assertFalse(t.is_alive())
        self.assertEqual(len(sent), 3)  # 2. kare 1.'nin aynısı, yutuldu
        self.assertTrue(all(m["data"]["lite"] and m["data"]["urls"] == ["https://e.test/login"] for m in sent))
        self.assertEqual([m["data"]["text"] for m in sent], ["v1\nv2", "v1\nv3", "v3\nv4"])


@unittest.skipUnless(shutil.which("tmux"), "tmux kurulu değil")
class RealTmuxCaptureTests(unittest.TestCase):
    """Kırpmanın KAYIPSIZ olduğunun kanıtı: tam capture'ın son `rows` satırı, görünür-ekran
    capture'ına birebir eşit (SGR durumu satır sonlarında taşınmıyor, newline kuralı doğru)."""

    SOCK = f"cops_test_term_lite_{os.getpid()}"

    def tmux(self, *args):
        return subprocess.run(["tmux", "-L", self.SOCK, *args], capture_output=True, text=True, timeout=10)

    def setUp(self):
        r = self.tmux("new-session", "-d", "-s", "t", "-x", "80", "-y", "10", "bash --norc --noprofile")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.addCleanup(self.tmux, "kill-server")

    def wait_for(self, needle, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if needle in self.tmux("capture-pane", "-t", "t", "-p").stdout:
                return True
            time.sleep(0.05)
        return False

    def test_last_rows_of_full_capture_equal_visible_capture(self):
        script = ('echo "login https://e.test/device?code=ZZ9"; '
                  'for i in $(seq 1 40); do echo "hist line $i"; done; '
                  'printf "\\033[31;1mRED-A\\nRED-B\\nRED-C\\n"; printf "plain-after-no-reset\\n"; echo DONE-$((6*7))')
        self.tmux("send-keys", "-t", "t", script, "Enter")
        # İğne ("DONE-42") yazılan komutun yankısında DEĞİL, yalnız çalışmış çıktıda oluşur.
        self.assertTrue(self.wait_for("DONE-42"), "çıktı gelmedi")
        rows = int(self.tmux("display-message", "-p", "-t", "t", "#{pane_height}").stdout.strip())
        hist = int(self.tmux("display-message", "-p", "-t", "t", "#{history_size}").stdout.strip())
        full = self.tmux("capture-pane", "-t", "t", "-e", "-p", "-S", "-2000").stdout
        visible = self.tmux("capture-pane", "-t", "t", "-e", "-p").stdout
        self.assertGreater(hist, 20, "scrollback oluşmadı, test anlamsız")
        self.assertTrue(full.endswith("\n") and visible.endswith("\n"))

        self.assertEqual(web_term_lite.viewport_text(full, rows), visible[:-1])

        lite = web_term_lite.to_lite(frame(full, rows=rows, history_size=hist))
        self.assertEqual(lite["text"], visible[:-1])
        self.assertEqual(lite["text"].count("\n") + 1, rows)
        self.assertGreater(len(full), 3 * len(lite["text"]), "kare küçülmedi")
        # URL yalnız scrollback'te (ekrandan çoktan kaydı) ama şeritte kalmalı.
        self.assertNotIn("e.test", lite["text"])
        self.assertIn("https://e.test/device?code=ZZ9", lite["urls"])


if __name__ == "__main__":
    unittest.main()

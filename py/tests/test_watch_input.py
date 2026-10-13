"""`py/cops watch` girdi kipleri testleri: yazı satırı (`i`), kısa tuş (`k`), ham geçiş (`R`); TBD#79.

Çalıştırma:  python3 -m unittest discover -s py/tests -p 'test_watch_input.py' -v

Birim testler sahte gönderici/saatle koşar (hiçbiri gerçekten beklemez); `InputSender` 127.0.0.1'de gerçek bir
stdlib HTTP sunucusuna, `Keys` gerçek bir pty'ye, en sonda tüm görüntüleyici (alt süreç, kontrol terminali olan bir
pty'de) sahte panele karşı koşar. Gerçek panele, tmux'a, kullanıcının terminaline DOKUNMAZ.
"""
import contextlib
import fcntl
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import watch  # noqa: E402
from claudeops.tmux_backend import ALLOWED_SPECIAL_KEYS  # noqa: E402

try:
    import pty
    import termios
except ImportError:  # pragma: no cover - Windows
    pty = termios = None

ESC = "\x1b"
PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def good(text="v1\nv2\nv3", cols=80, rows=3, **extra):
    base = {"ok": True, "text": text, "cols": cols, "rows": rows, "lite": True,
            "history_size": 0, "alternate_screen": False, "masked": False, "mode": None,
            "urls": [], "paths": []}
    base.update(extra)
    return base


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_screen(size=(80, 6)):
    out = io.StringIO()
    screen = watch.Screen(out, title="yuhem:s1", size_fn=lambda: size)
    return screen, out


class FakeSender:
    """`InputSender` yerine: gönderilenleri kaydeder, sonuçları testin istediği anda verir."""

    def __init__(self):
        self.sent = []
        self._results = []
        self.closed = False

    def submit(self, kind, payload):
        self.sent.append((kind, payload))
        return len(self.sent)

    def take_results(self):
        out, self._results = self._results, []
        return out

    def finish(self, seq, ok=True, err=""):
        self._results.append((seq, self.sent[seq - 1][0], ok, err))

    def close(self, wait=2.0):
        self.closed = True


class FakeKeys:
    """`Keys` yerine: yalnız ham geçiş geçişlerini kaydeder."""

    def __init__(self):
        self.passthrough = []

    def set_passthrough(self, on):
        self.passthrough.append(on)


class Rig:
    """Gerçek `Viewer` + `InputController`, sahte gönderici/saat/ekran."""

    def __init__(self, size=(80, 6), live=True, **frame_extra):
        self.clock = Clock()
        self.screen, self.out = make_screen(size)
        self.viewer = watch.Viewer("yuhem", "s1", self.screen, clock=self.clock)
        self.sender = FakeSender()
        self.keys = FakeKeys()
        self.ctl = watch.InputController(self.viewer, self.sender, keys=self.keys, clock=self.clock)
        self.viewer.overlay = self.ctl.bar
        if live:
            self.viewer.apply_frame(good(**frame_extra))

    def press(self, *chunks):
        result = False
        for chunk in chunks:
            result = self.ctl.handle(chunk)
        return result

    def bar(self, cols=80):
        return self.ctl.bar(cols)

    def bar_text(self, cols=80):
        bar = self.ctl.bar(cols)
        return bar[0] if bar else None

    def advance(self, seconds):
        self.clock.now += seconds


# ── tuş ayrıştırma ve yazı yardımcıları ─────────────────────────────────────────────────────

class KeyParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = watch.KeyParser()

    def test_plain_characters(self):
        self.assertEqual(self.parser.feed("ab"), ["a", "b"])

    def test_turkish_characters_are_single_tokens(self):
        self.assertEqual(self.parser.feed("şğü"), ["ş", "ğ", "ü"])

    def test_arrow_and_function_sequences_are_one_token_each(self):
        self.assertEqual(self.parser.feed(f"{ESC}[A{ESC}OP{ESC}[1;2Q"), [f"{ESC}[A", f"{ESC}OP", f"{ESC}[1;2Q"])

    def test_a_lone_escape_is_the_escape_key(self):
        self.assertEqual(self.parser.feed(ESC), [ESC])

    def test_escape_followed_by_a_character_is_an_alt_combination(self):
        self.assertEqual(self.parser.feed(f"{ESC}x"), [f"{ESC}x"])

    def test_bracketed_paste_becomes_one_paste_token(self):
        toks = self.parser.feed(f"a{ESC}[200~hello\nworld{ESC}[201~b")
        self.assertEqual(toks, ["a", "hello\nworld", "b"])
        self.assertIsInstance(toks[1], watch.Paste)
        self.assertNotIsInstance(toks[0], watch.Paste)

    def test_paste_can_span_several_reads(self):
        self.assertEqual(self.parser.feed(f"{ESC}[200~par"), [])
        self.assertEqual(self.parser.feed("t one "), [])
        toks = self.parser.feed(f"two{ESC}[201~q")
        self.assertEqual(toks, ["part one two", "q"])
        self.assertIsInstance(toks[0], watch.Paste)

    def test_an_unterminated_paste_expires_instead_of_swallowing_every_later_key(self):
        self.assertEqual(self.parser.feed(f"{ESC}[200~abc", now=0.0), [])
        self.assertEqual(self.parser.feed("q", now=1.0), [])   # hâlâ yapıştırmanın içi
        self.assertEqual(self.parser.feed("q", now=watch.PASTE_STALE_SECONDS + 1), ["q"])

    def test_an_oversized_paste_is_dropped_whole_not_truncated(self):
        with mock.patch.object(watch, "PASTE_MAX_CHARS", 10):
            toks = self.parser.feed(f"{ESC}[200~{'x' * 11}{ESC}[201~q")
        self.assertEqual(toks, ["q"])

    def test_an_empty_paste_is_an_empty_token(self):
        toks = self.parser.feed(f"{ESC}[200~{ESC}[201~")
        self.assertEqual(toks, [""])
        self.assertIsInstance(toks[0], watch.Paste)

    def test_an_end_marker_without_a_start_is_just_an_ignored_sequence(self):
        self.assertEqual(self.parser.feed(f"{ESC}[201~"), [f"{ESC}[201~"])


class TextHelperTests(unittest.TestCase):
    def test_one_line_turns_line_breaks_and_tabs_into_spaces(self):
        self.assertEqual(watch.one_line("a\nb\tc"), "a b c")
        self.assertEqual(watch.one_line("a\r\nb"), "a  b")

    def test_one_line_drops_other_control_characters(self):
        self.assertEqual(watch.one_line("a\x07b\x1bc\x7fd"), "abcd")

    def test_drop_last_char(self):
        self.assertEqual(watch.drop_last_char("abc"), "ab")
        self.assertEqual(watch.drop_last_char(""), "")

    def test_drop_last_char_takes_the_combining_mark_with_its_base(self):
        self.assertEqual(watch.drop_last_char("aé"), "a")
        self.assertEqual(watch.drop_last_char("é"), "")

    def test_drop_last_word(self):
        self.assertEqual(watch.drop_last_word("foo bar"), "foo ")
        self.assertEqual(watch.drop_last_word("foo bar   "), "foo ")
        self.assertEqual(watch.drop_last_word("foo"), "")
        self.assertEqual(watch.drop_last_word(""), "")

    def test_tail_fit_keeps_a_short_text_whole(self):
        self.assertEqual(watch.tail_fit("hello", 10), "hello")
        self.assertEqual(watch.tail_fit("hello", 5), "hello")

    def test_tail_fit_keeps_the_end_and_marks_the_cut(self):
        out = watch.tail_fit("abcdefghij", 6)
        self.assertEqual(out, "…fghij")
        self.assertLessEqual(watch.display_width(out), 6)

    def test_tail_fit_counts_wide_characters_as_two_columns(self):
        out = watch.tail_fit("日本語", 5)
        self.assertEqual(out, "…本語")
        self.assertLessEqual(watch.display_width(out), 5)
        self.assertEqual(watch.tail_fit("日本語", 4), "…語")

    def test_tail_fit_zero_width(self):
        self.assertEqual(watch.tail_fit("abc", 0), "")


# ── gönderici (gerçek HTTP) ─────────────────────────────────────────────────────────────────

class PostPanel:
    """Gerçek bir HTTP sunucusu (127.0.0.1, rastgele port): POST'ları sırayla kaydeder."""

    def __init__(self, token="tok", responder=None, delay=0.0):
        self.token = token
        self.responder = responder or (lambda path, body: (200, {"ok": True}))
        self.delay = delay
        self.posts = []
        panel = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                auth = self.headers.get("Authorization")
                panel.posts.append({"path": self.path, "body": body, "auth": auth,
                                    "ctype": self.headers.get("Content-Type")})
                if panel.delay:
                    time.sleep(panel.delay)
                if auth != f"Bearer {panel.token}":
                    status, obj = 401, {"ok": False, "error": "unauthorized"}
                else:
                    status, obj = panel.responder(self.path, body)
                data = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def wait_results(sender, count, timeout=5.0):
    got, end = [], time.time() + timeout
    while len(got) < count and time.time() < end:
        got += sender.take_results()
        time.sleep(0.005)
    return got


class InputSenderTests(unittest.TestCase):
    def make(self, panel, token="tok", **kw):
        sender = watch.InputSender(panel.port, "yuhem", "s1", read_token=lambda: token, **kw)
        self.addCleanup(sender.close, 0.5)
        return sender

    def setUp(self):
        self.panel = PostPanel()
        self.addCleanup(self.panel.close)

    def test_each_kind_goes_to_its_endpoint_with_its_field(self):
        sender = self.make(self.panel)
        for kind, payload in (("text", "merhaba"), ("key", "Enter"), ("raw", "ls\r")):
            sender.submit(kind, payload)
        wait_results(sender, 3)
        self.assertEqual([(p["path"], p["body"]) for p in self.panel.posts], [
            ("/api/term/input", {"name": "s1", "host": "yuhem", "text": "merhaba", "lang": "en"}),
            ("/api/term/key", {"name": "s1", "host": "yuhem", "key": "Enter", "lang": "en"}),
            ("/api/term/raw", {"name": "s1", "host": "yuhem", "data": "ls\r", "lang": "en"}),
        ])

    def test_request_carries_the_bearer_token_and_json_content_type(self):
        sender = self.make(self.panel)
        sender.submit("text", "x")
        wait_results(sender, 1)
        self.assertEqual(self.panel.posts[0]["auth"], "Bearer tok")
        self.assertEqual(self.panel.posts[0]["ctype"], "application/json")

    def test_results_pair_the_sequence_number_with_the_outcome(self):
        sender = self.make(self.panel)
        first, second = sender.submit("text", "a"), sender.submit("key", "Tab")
        results = wait_results(sender, 2)
        self.assertEqual(results, [(first, "text", True, ""), (second, "key", True, "")])
        self.assertEqual(sender.take_results(), [])   # bir kez alınır

    def test_non_ascii_text_survives(self):
        sender = self.make(self.panel)
        sender.submit("text", "şğüİ 日本")
        wait_results(sender, 1)
        self.assertEqual(self.panel.posts[0]["body"]["text"], "şğüİ 日本")

    def test_ok_false_body_is_an_error_with_the_panels_message(self):
        panel = PostPanel(responder=lambda path, body: (200, {"ok": False, "error": "oturum yok"}))
        self.addCleanup(panel.close)
        sender = self.make(panel)
        seq = sender.submit("text", "a")
        self.assertEqual(wait_results(sender, 1), [(seq, "text", False, "oturum yok")])

    def test_ok_false_without_a_message_still_says_something(self):
        panel = PostPanel(responder=lambda path, body: (200, {"ok": False}))
        self.addCleanup(panel.close)
        sender = self.make(panel)
        sender.submit("text", "a")
        self.assertTrue(wait_results(sender, 1)[0][3])

    def test_wrong_token_is_reported_as_a_token_mismatch(self):
        sender = self.make(self.panel, token="yanlis")
        sender.submit("text", "a")
        ok, err = wait_results(sender, 1)[0][2:]
        self.assertFalse(ok)
        self.assertIn("401", err)
        self.assertIn("web.token", err)

    def test_other_http_errors(self):
        panel = PostPanel(responder=lambda path, body: (500, {"ok": False}))
        self.addCleanup(panel.close)
        sender = self.make(panel)
        sender.submit("text", "a")
        self.assertEqual(wait_results(sender, 1)[0][2:], (False, "http 500"))

    def test_non_json_reply(self):
        panel = PostPanel(responder=lambda path, body: (200, b"<html>"))
        self.addCleanup(panel.close)
        sender = self.make(panel)
        sender.submit("text", "a")
        self.assertEqual(wait_results(sender, 1)[0][2:], (False, "panel JSON olmayan yanıt verdi"))

    def test_panel_down_is_an_error_not_a_crash(self):
        panel = PostPanel()
        port = panel.port
        panel.close()
        sender = watch.InputSender(port, "yuhem", "s1", read_token=lambda: "tok")
        self.addCleanup(sender.close, 0.5)
        sender.submit("text", "a")
        ok, err = wait_results(sender, 1)[0][2:]
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_an_unreadable_token_is_an_error_and_the_thread_survives(self):
        def broken():
            raise watch.TransportError("web.token okunamadı", auth=True)

        sender = watch.InputSender(self.panel.port, "yuhem", "s1", read_token=broken)
        self.addCleanup(sender.close, 0.5)
        sender.submit("text", "a")
        self.assertEqual(wait_results(sender, 1)[0][2:], (False, "web.token okunamadı"))
        self.assertEqual(self.panel.posts, [])
        sender._read_token = lambda: "tok"   # sonraki gönderim yine çalışır
        sender.submit("text", "b")
        self.assertTrue(wait_results(sender, 1)[0][2])

    def test_an_unexpected_exception_does_not_kill_the_sender(self):
        calls = []

        def urlopen(req, timeout=None):
            calls.append(req)
            if len(calls) == 1:
                raise RuntimeError("beklenmedik")
            raise urllib.error.URLError("kapali")

        sender = watch.InputSender(1, "yuhem", "s1", read_token=lambda: "tok", urlopen=urlopen)
        self.addCleanup(sender.close, 0.5)
        sender.submit("text", "a")
        sender.submit("text", "b")
        results = wait_results(sender, 2)
        self.assertEqual([r[2] for r in results], [False, False])
        self.assertIn("iç hata", results[0][3])
        self.assertEqual(results[1][3], "kapali")

    def test_requests_arrive_in_submission_order(self):
        panel = PostPanel(responder=lambda path, body: (time.sleep(0.01 * (hash(body["data"]) % 3)) or 200, {"ok": True}))
        self.addCleanup(panel.close)
        sender = self.make(panel)
        for i in range(12):
            sender.submit("raw", f"k{i}")
        wait_results(sender, 12)
        self.assertEqual([p["body"]["data"] for p in panel.posts], [f"k{i}" for i in range(12)])

    def test_the_token_is_re_read_for_every_request(self):
        tokens = iter(["tok", "tok", "baska"])
        sender = watch.InputSender(self.panel.port, "yuhem", "s1", read_token=lambda: next(tokens))
        self.addCleanup(sender.close, 0.5)
        sender.submit("text", "a")
        sender.submit("text", "b")
        sender.submit("text", "c")
        results = wait_results(sender, 3)
        self.assertEqual([r[2] for r in results], [True, True, False])

    def test_unknown_kind_is_a_programming_error(self):
        sender = self.make(self.panel)
        with self.assertRaises(ValueError):
            sender.submit("nope", "x")
        self.assertEqual(sender.inflight(), 0)

    def test_submit_returns_immediately_and_inflight_drains(self):
        panel = PostPanel(delay=0.3)
        self.addCleanup(panel.close)
        sender = self.make(panel)
        t0 = time.time()
        sender.submit("text", "a")
        self.assertLess(time.time() - t0, 0.15)   # HTTP çağrısı çizim döngüsünü beklemez
        self.assertEqual(sender.inflight(), 1)
        wait_results(sender, 1)
        self.assertEqual(sender.inflight(), 0)

    def test_close_lets_the_pending_message_go_out(self):
        panel = PostPanel(delay=0.2)
        self.addCleanup(panel.close)
        sender = watch.InputSender(panel.port, "yuhem", "s1", read_token=lambda: "tok")
        sender.submit("text", "son mesaj")
        sender.close(wait=3.0)
        self.assertEqual([p["body"]["text"] for p in panel.posts], ["son mesaj"])

    def test_close_without_any_submit_is_a_no_op(self):
        watch.InputSender(1, "yuhem", "s1").close(0.1)


# ── Keys (gerçek pty) ───────────────────────────────────────────────────────────────────────

@unittest.skipIf(pty is None, "pty yok")
class KeysPtyTests(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = pty.openpty()
        self.stream = os.fdopen(os.dup(self.slave), "r")
        self.addCleanup(self.close_all)

    def close_all(self):
        for closer in (self.stream.close, lambda: os.close(self.master), lambda: os.close(self.slave)):
            with contextlib.suppress(OSError):
                closer()

    def flags(self):
        attrs = termios.tcgetattr(self.slave)
        return attrs[0], attrs[3]

    def read(self, keys, want, timeout=2.0):
        got, end = "", time.time() + timeout
        while len(got) < want and time.time() < end:
            got += keys.poll()
            time.sleep(0.005)
        return got

    def test_cbreak_state_and_exact_restore(self):
        before = termios.tcgetattr(self.slave)
        with watch.Keys(self.stream):
            iflag, lflag = self.flags()
            self.assertFalse(lflag & termios.ECHO)
            self.assertFalse(lflag & termios.ICANON)
            self.assertTrue(lflag & termios.ISIG)      # Ctrl-C normal kipte görüntüleyiciyi hâlâ kapatır
            self.assertTrue(iflag & termios.ICRNL)
        self.assertEqual(termios.tcgetattr(self.slave), before)

    def test_poll_decodes_utf8(self):
        with watch.Keys(self.stream) as keys:
            os.write(self.master, "şğ".encode())
            self.assertEqual(self.read(keys, 2), "şğ")

    def test_a_multibyte_character_split_across_reads_is_not_lost(self):
        with watch.Keys(self.stream) as keys:
            os.write(self.master, b"\xc5")
            time.sleep(0.05)
            self.assertEqual(keys.poll(), "")
            os.write(self.master, b"\x9f")
            self.assertEqual(self.read(keys, 1), "ş")

    def test_enter_arrives_as_newline_in_cbreak(self):
        with watch.Keys(self.stream) as keys:
            os.write(self.master, b"\r")
            self.assertEqual(self.read(keys, 1), "\n")

    def test_passthrough_turns_off_signals_and_carriage_return_translation(self):
        with watch.Keys(self.stream) as keys:
            cbreak = self.flags()
            keys.set_passthrough(True)
            iflag, lflag = self.flags()
            self.assertFalse(lflag & termios.ISIG)
            self.assertFalse(lflag & termios.IEXTEN)
            self.assertFalse(iflag & (termios.ICRNL | termios.INLCR | termios.IXON))
            os.write(self.master, b"\r\x03\x13")
            self.assertEqual(self.read(keys, 3), "\r\x03\x13")   # Enter \r, Ctrl-C ve Ctrl-S olduğu gibi
            keys.set_passthrough(False)
            self.assertEqual(self.flags(), cbreak)

    def test_exit_after_passthrough_restores_the_original_state(self):
        before = termios.tcgetattr(self.slave)
        with watch.Keys(self.stream) as keys:
            keys.set_passthrough(True)
        self.assertEqual(termios.tcgetattr(self.slave), before)

    def test_a_non_tty_stream_is_inert(self):
        with watch.Keys(io.StringIO()) as keys:
            keys.set_passthrough(True)
            keys.set_passthrough(False)
            self.assertEqual(keys.poll(), "")


# ── yazı satırı ─────────────────────────────────────────────────────────────────────────────

class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()

    def test_i_opens_the_line_and_echoes_locally_without_sending(self):
        self.rig.press("i")
        self.assertEqual(self.rig.ctl.mode, "compose")
        self.rig.press("mer")
        text, style = self.rig.bar()
        self.assertIn("✎ ▸ mer█", text)
        self.assertEqual(style, watch.STYLE_INPUT)
        self.assertEqual(self.rig.sender.sent, [])

    def test_enter_sends_one_message_and_closes_the_line(self):
        self.rig.press("iselam\r")
        self.assertEqual(self.rig.sender.sent, [("text", "selam")])
        self.assertEqual(self.rig.ctl.mode, "normal")
        self.assertEqual(self.rig.ctl.buf, "")

    def test_enter_as_a_newline_character_also_sends(self):
        self.rig.press("iselam\n")
        self.assertEqual(self.rig.sender.sent, [("text", "selam")])

    def test_the_message_is_stripped(self):
        self.rig.press("i  merhaba dünya  \r")
        self.assertEqual(self.rig.sender.sent, [("text", "merhaba dünya")])

    def test_an_empty_or_blank_line_sends_nothing_and_stays_open(self):
        self.rig.press("i\r", "   \r")
        self.assertEqual(self.rig.sender.sent, [])
        self.assertEqual(self.rig.ctl.mode, "compose")

    def test_escape_cancels_without_sending_and_forgets_the_text(self):
        self.rig.press("itaslak", ESC)
        self.assertEqual(self.rig.ctl.mode, "normal")
        self.assertEqual(self.rig.sender.sent, [])
        self.rig.press("i")
        self.assertEqual(self.rig.ctl.buf, "")

    def test_q_x_and_the_other_command_keys_are_text_while_composing(self):
        self.assertFalse(self.rig.press("iqxkRi"))
        self.assertEqual(self.rig.ctl.buf, "qxkRi")
        self.assertEqual(self.rig.ctl.mode, "compose")

    def test_backspace_ctrl_u_and_ctrl_w(self):
        self.rig.press("iabc\x7f")
        self.assertEqual(self.rig.ctl.buf, "ab")
        self.rig.press("\x08")
        self.assertEqual(self.rig.ctl.buf, "a")
        self.rig.press("foo bar\x17")
        self.assertEqual(self.rig.ctl.buf, "afoo ")
        self.rig.press("\x15")
        self.assertEqual(self.rig.ctl.buf, "")
        self.rig.press("\x7f")   # boşta silme sorun çıkarmaz
        self.assertEqual(self.rig.ctl.buf, "")

    def test_turkish_characters(self):
        self.rig.press("işğüÇÖ\r")
        self.assertEqual(self.rig.sender.sent, [("text", "şğüÇÖ")])

    def test_arrow_function_and_alt_keys_are_ignored(self):
        self.rig.press(f"iab{ESC}[A{ESC}OP{ESC}xc")
        self.assertEqual(self.rig.ctl.buf, "abc")

    def test_other_control_characters_are_ignored(self):
        self.rig.press("ia\x01\x07\tb")
        self.assertEqual(self.rig.ctl.buf, "ab")

    def test_pasted_text_is_one_line(self):
        self.rig.press(f"i{ESC}[200~a\nb\tc{ESC}[201~\r")
        self.assertEqual(self.rig.sender.sent, [("text", "a b c")])

    def test_pasted_text_never_submits_early(self):
        self.rig.press(f"i{ESC}[200~birinci\nikinci\n{ESC}[201~")
        self.assertEqual(self.rig.sender.sent, [])
        self.assertEqual(self.rig.ctl.mode, "compose")

    def test_the_line_is_capped(self):
        with mock.patch.object(watch, "COMPOSE_MAX_CHARS", 5):
            self.rig.press("i1234567890")
        self.assertEqual(self.rig.ctl.buf, "12345")

    def test_a_long_line_shows_its_tail_within_the_bar_width(self):
        self.rig.press("i" + "a" * 80 + "SON")
        for cols in (80, 40, 24):
            text, _ = self.rig.bar(cols)
            self.assertLessEqual(watch.display_width(text), cols)
            self.assertIn("SON█", text)
            self.assertIn("…", text)

    def test_the_hint_sits_at_the_right_edge_when_there_is_room(self):
        self.rig.press("ihi")
        text, _ = self.rig.bar(80)
        self.assertTrue(text.endswith("⏎ gönder · Esc iptal"))
        self.assertEqual(watch.display_width(text), 79)

    def test_a_narrow_bar_drops_the_hint_before_the_text(self):
        self.rig.press("ihi")
        text, _ = self.rig.bar(24)
        self.assertNotIn("gönder", text)
        self.assertIn("hi█", text)

    def test_the_hint_warns_when_the_connection_is_down(self):
        self.rig.press("ihi")
        self.rig.viewer.apply_failure("ConnectionRefusedError")
        text, _ = self.rig.bar(100)
        self.assertIn("bağlantı canlı değil: gönderilmez", text)
        self.assertIn("hi█", text)

    def test_wide_characters_fit_the_bar(self):
        self.rig.press("i" + "日本語" * 30)
        text, _ = self.rig.bar(40)
        self.assertLessEqual(watch.display_width(text), 40)


class SendGateTests(unittest.TestCase):
    """Bağlantı canlı değilken ya da pane maskeliyken HİÇBİR şey yollanmaz (CLAUDE.md tmux kuralı + TBD#79)."""

    def test_not_live_blocks_the_message_and_keeps_the_line(self):
        rig = Rig()
        rig.viewer.apply_failure("ConnectionRefusedError")
        rig.press("iselam\r")
        self.assertEqual(rig.sender.sent, [])
        self.assertEqual(rig.ctl.mode, "compose")
        self.assertEqual(rig.ctl.buf, "selam")
        text, style = rig.bar()
        self.assertIn("bağlantı canlı değil", text)
        self.assertEqual(style, watch.STYLE_SEVERE)

    def test_the_kept_line_goes_out_once_the_connection_is_back(self):
        rig = Rig()
        rig.viewer.apply_failure("x")
        rig.press("iselam\r")
        rig.viewer.apply_frame(good())
        rig.press("\r")
        self.assertEqual(rig.sender.sent, [("text", "selam")])

    def test_the_error_clears_at_the_next_key_and_the_line_comes_back(self):
        rig = Rig()
        rig.viewer.apply_failure("x")
        rig.press("ia\r")
        self.assertIn("gönderilmedi", rig.bar_text())
        rig.press("b")
        self.assertIn("✎ ▸ ab█", rig.bar_text())

    def test_waiting_state_blocks_too(self):
        rig = Rig()
        rig.viewer.apply_frame({"ok": False, "error": "s1: not running"})
        rig.press("ia\r")
        self.assertEqual(rig.sender.sent, [])

    def test_no_frame_yet_blocks(self):
        rig = Rig(live=False)
        rig.press("ia\r")
        self.assertEqual(rig.sender.sent, [])
        self.assertIn("gönderilmedi", rig.bar_text())

    def test_masked_input_blocks_the_message(self):
        rig = Rig(masked=True)
        rig.press("iparola\r")
        self.assertEqual(rig.sender.sent, [])
        text, style = rig.bar(120)
        self.assertIn("maskeli", text)
        self.assertEqual(style, watch.STYLE_SEVERE)

    def test_masked_input_blocks_short_keys(self):
        rig = Rig(masked=True)
        rig.press("k", "\n")
        self.assertEqual(rig.sender.sent, [])

    def test_masked_input_blocks_raw_keys(self):
        rig = Rig(masked=True)
        rig.press("R", "\n", "abc")
        self.assertEqual(rig.sender.sent, [])

    def test_the_error_flash_expires(self):
        rig = Rig()
        rig.viewer.apply_failure("x")
        rig.press("ia\r")
        rig.press(ESC)   # kipten çık, çubukta yalnız bildirim kalsın
        rig.press("")
        self.assertIsNone(rig.bar())   # bildirim kipten çıkışta zaten sönük (compose'da ilk tuşta silinmişti)


class FlashTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.rig.press("iselam\r")

    def test_sending_is_shown_until_the_result_arrives(self):
        text, style = self.rig.bar()
        self.assertEqual(text, " … mesaj gönderiliyor")
        self.assertEqual(style, watch.STYLE_INPUT)

    def test_success_flashes_green_then_disappears(self):
        self.rig.sender.finish(1)
        self.rig.press("")
        self.assertEqual(self.rig.bar(), (" ✓ mesaj gönderildi", watch.STYLE_LIVE))
        self.rig.advance(watch.FLASH_OK_SECONDS + 0.1)
        self.rig.press("")
        self.assertIsNone(self.rig.bar())

    def test_failure_flashes_red_with_the_reason_for_longer(self):
        self.rig.sender.finish(1, ok=False, err="oturum yok")
        self.rig.press("")
        self.assertEqual(self.rig.bar(), (" ✗ mesaj gönderilemedi: oturum yok", watch.STYLE_SEVERE))
        self.rig.advance(watch.FLASH_OK_SECONDS + 0.1)
        self.assertIsNotNone(self.rig.bar())
        self.rig.advance(watch.FLASH_ERR_SECONDS)
        self.assertIsNone(self.rig.bar())

    def test_control_characters_in_an_error_never_reach_the_bar(self):
        self.rig.sender.finish(1, ok=False, err="kötü\x1b[31m\nsatır")
        self.rig.press("")
        self.assertNotIn(ESC, self.rig.bar_text())
        self.assertNotIn("\n", self.rig.bar_text())

    def test_the_status_bar_is_back_after_the_flash(self):
        self.rig.sender.finish(1)
        self.rig.press("")
        self.rig.advance(5)
        self.rig.screen.dead = False
        self.rig.viewer.render()
        self.assertIn("canlı", self.rig.out.getvalue())


# ── kısa tuş ────────────────────────────────────────────────────────────────────────────────

class ShortKeyTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()

    def test_k_then_one_key_sends_it_and_closes_the_mode(self):
        self.rig.press("k")
        self.assertEqual(self.rig.ctl.mode, "keys")
        text, style = self.rig.bar()
        self.assertIn("kısa tuş", text)
        self.assertEqual(style, watch.STYLE_INPUT)
        self.rig.press("\n")
        self.assertEqual(self.rig.sender.sent, [("key", "Enter")])
        self.assertEqual(self.rig.ctl.mode, "normal")

    def test_every_key_of_the_medium_set_maps_to_the_panels_name(self):
        cases = {"\r": "Enter", "\n": "Enter", ESC: "Escape", "\t": "Tab", f"{ESC}[Z": "BTab",
                 f"{ESC}[A": "Up", f"{ESC}[B": "Down", f"{ESC}[C": "Right", f"{ESC}[D": "Left",
                 f"{ESC}OA": "Up", f"{ESC}OB": "Down", f"{ESC}OC": "Right", f"{ESC}OD": "Left"}
        for token, name in cases.items():
            rig = Rig()
            rig.press("k", token)
            self.assertEqual(rig.sender.sent, [("key", name)], token)

    def test_the_short_keys_are_all_names_the_panel_accepts_and_never_ctrl_c_or_ctrl_d(self):
        names = set(watch.InputController.SHORT_KEYS.values())
        self.assertTrue(names <= ALLOWED_SPECIAL_KEYS)
        self.assertFalse(names & {"C-c", "C-d"})
        self.assertEqual(names, {"Enter", "Escape", "Tab", "BTab", "Up", "Down", "Left", "Right"})

    def test_every_name_has_a_label_for_the_status_bar(self):
        for name in set(watch.InputController.SHORT_KEYS.values()):
            self.assertIn(name, watch.InputController.KEY_LABELS)

    def test_an_unmapped_key_cancels_without_sending(self):
        self.rig.press("k", "a")
        self.assertEqual(self.rig.sender.sent, [])
        self.assertEqual(self.rig.ctl.mode, "normal")

    def test_ctrl_c_and_ctrl_d_characters_are_not_short_keys(self):
        self.rig.press("k", "\x04")
        self.assertEqual(self.rig.sender.sent, [])

    def test_q_in_the_mode_cancels_and_does_not_quit(self):
        self.assertFalse(self.rig.press("k", "q"))
        self.assertEqual(self.rig.ctl.mode, "normal")

    def test_k_again_cancels(self):
        self.rig.press("k", "k")
        self.assertEqual(self.rig.ctl.mode, "normal")
        self.assertEqual(self.rig.sender.sent, [])

    def test_only_one_key_per_k(self):
        self.rig.press("k\n\n\n")
        self.assertEqual(self.rig.sender.sent, [("key", "Enter")])

    def test_a_pasted_block_cancels(self):
        self.rig.press("k", f"{ESC}[200~x{ESC}[201~")
        self.assertEqual(self.rig.ctl.mode, "normal")
        self.assertEqual(self.rig.sender.sent, [])

    def test_a_pasted_line_break_or_tab_is_not_a_short_key(self):
        for pasted in ("\n", "\r", "\t", ESC):
            rig = Rig()
            rig.press("k", f"{ESC}[200~{pasted}{ESC}[201~")
            self.assertEqual(rig.sender.sent, [], repr(pasted))
            self.assertEqual(rig.ctl.mode, "normal", repr(pasted))

    def test_the_mode_times_out_without_sending(self):
        self.rig.press("k")
        self.rig.advance(watch.KEYS_MODE_SECONDS + 0.1)
        self.rig.press("")
        self.assertEqual(self.rig.ctl.mode, "normal")
        self.rig.press("\n")
        self.assertEqual(self.rig.sender.sent, [])

    def test_a_key_just_before_the_timeout_still_goes(self):
        self.rig.press("k")
        self.rig.advance(watch.KEYS_MODE_SECONDS - 0.5)
        self.rig.press("\n")
        self.assertEqual(self.rig.sender.sent, [("key", "Enter")])

    def test_not_live_blocks_and_says_so(self):
        self.rig.viewer.apply_failure("x")
        self.rig.press("k", "\n")
        self.assertEqual(self.rig.sender.sent, [])
        self.assertIn("gönderilmedi", self.rig.bar_text())

    def test_the_result_is_named_after_the_key(self):
        self.rig.press("k", f"{ESC}[B")
        self.assertEqual(self.rig.bar_text(), " … ↓ gönderiliyor")
        self.rig.sender.finish(1)
        self.rig.press("")
        self.assertEqual(self.rig.bar_text(), " ✓ ↓ gönderildi")


# ── ham geçiş ───────────────────────────────────────────────────────────────────────────────

class RawModeTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()

    def enter_raw(self):
        self.rig.press("R", "\n")

    def test_capital_r_asks_for_confirmation_and_does_not_open_yet(self):
        self.rig.press("R")
        self.assertEqual(self.rig.ctl.mode, "rawask")
        text, style = self.rig.bar(120)
        self.assertIn("HAM GEÇİŞ açılsın mı", text)
        self.assertEqual(style, watch.STYLE_RAW)
        self.assertEqual(self.rig.keys.passthrough, [])

    def test_lowercase_r_does_nothing(self):
        self.rig.press("r")
        self.assertEqual(self.rig.ctl.mode, "normal")

    def test_anything_but_enter_declines(self):
        for token in (ESC, "a", "y", "q", "R", f"{ESC}[A"):
            rig = Rig()
            self.assertFalse(rig.press("R", token))
            self.assertEqual(rig.ctl.mode, "normal", token)
            self.assertEqual(rig.keys.passthrough, [], token)

    def test_a_pasted_line_break_does_not_confirm(self):
        for pasted in ("\n", "\r"):
            rig = Rig()
            rig.press("R", f"{ESC}[200~{pasted}{ESC}[201~")
            self.assertEqual(rig.ctl.mode, "normal", repr(pasted))
            self.assertEqual(rig.keys.passthrough, [], repr(pasted))

    def test_a_pasted_exit_key_is_data_not_a_command(self):
        self.enter_raw()
        self.rig.press(f"{ESC}[200~\x1d{ESC}[201~")
        self.assertEqual(self.rig.ctl.mode, "raw")
        self.assertEqual(self.rig.sender.sent, [("raw", "\x1d")])

    def test_the_confirmation_times_out(self):
        self.rig.press("R")
        self.rig.advance(watch.RAW_CONFIRM_SECONDS + 0.1)
        self.rig.press("")
        self.assertEqual(self.rig.ctl.mode, "normal")
        self.rig.press("\n")
        self.assertEqual(self.rig.keys.passthrough, [])

    def test_confirming_opens_the_mode_and_switches_the_terminal_to_passthrough(self):
        self.enter_raw()
        self.assertEqual(self.rig.ctl.mode, "raw")
        self.assertEqual(self.rig.keys.passthrough, [True])
        text, style = self.rig.bar(120)
        self.assertEqual(style, watch.STYLE_RAW)
        self.assertIn("HAM GEÇİŞ", text)
        self.assertIn("Ctrl-]", text)

    def test_every_key_goes_through_in_one_batch_per_poll(self):
        self.enter_raw()
        self.rig.press(f"ab\x03\r{ESC}[A")
        self.assertEqual(self.rig.sender.sent, [("raw", f"ab\x03\r{ESC}[A")])

    def test_each_poll_is_its_own_request_in_order(self):
        self.enter_raw()
        self.rig.press("a", "b", "c")
        self.assertEqual(self.rig.sender.sent, [("raw", "a"), ("raw", "b"), ("raw", "c")])

    def test_the_command_keys_are_plain_input_in_raw_mode(self):
        self.enter_raw()
        self.assertFalse(self.rig.press("q"))
        self.assertFalse(self.rig.press("x"))
        self.assertFalse(self.rig.press("i"))
        self.assertEqual(self.rig.sender.sent, [("raw", "q"), ("raw", "x"), ("raw", "i")])
        self.assertEqual(self.rig.ctl.mode, "raw")

    def test_ctrl_right_bracket_leaves_and_restores_the_terminal(self):
        self.enter_raw()
        self.rig.press("ab\x1d")
        self.assertEqual(self.rig.sender.sent, [("raw", "ab")])   # çıkıştan ÖNCEKİ tuşlar gider
        self.assertEqual(self.rig.ctl.mode, "normal")
        self.assertEqual(self.rig.keys.passthrough, [True, False])
        self.assertEqual(self.rig.bar_text(), " ham geçiş kapandı")

    def test_keys_after_the_exit_key_in_the_same_read_are_normal_mode_keys(self):
        self.enter_raw()
        self.assertTrue(self.rig.press("a\x1dq"))   # Ctrl-]'dan sonraki q artık çıkış
        self.assertEqual(self.rig.sender.sent, [("raw", "a")])

    def test_idle_lock_closes_the_mode(self):
        self.enter_raw()
        self.rig.advance(watch.RAW_IDLE_LOCK_SECONDS + 1)
        self.rig.press("")
        self.assertEqual(self.rig.ctl.mode, "normal")
        self.assertEqual(self.rig.keys.passthrough, [True, False])
        self.assertIn("kilitlendi", self.rig.bar_text())
        self.rig.press("a")   # kilitliyken tuş oturuma GİTMEZ
        self.assertEqual(self.rig.sender.sent, [])

    def test_typing_keeps_the_lock_away(self):
        self.enter_raw()
        self.rig.advance(50)
        self.rig.press("a")
        self.rig.advance(50)
        self.rig.press("")
        self.assertEqual(self.rig.ctl.mode, "raw")
        self.rig.advance(watch.RAW_IDLE_LOCK_SECONDS - 49)
        self.rig.press("")
        self.assertEqual(self.rig.ctl.mode, "normal")

    def test_countdown_appears_only_near_the_lock(self):
        self.enter_raw()
        self.assertNotIn("kilitlenir", self.rig.bar_text(120))
        self.rig.advance(watch.RAW_IDLE_LOCK_SECONDS - watch.RAW_COUNTDOWN_SECONDS + 1)
        self.assertIn("14 sn sonra kilitlenir", self.rig.bar_text(120))
        self.rig.advance(10)
        self.assertIn("4 sn sonra kilitlenir", self.rig.bar_text(120))

    def test_a_single_line_paste_is_forwarded_as_typed(self):
        self.enter_raw()
        self.rig.press(f"{ESC}[200~ls -la{ESC}[201~")
        self.assertEqual(self.rig.sender.sent, [("raw", "ls -la")])

    def test_a_multi_line_paste_is_refused_not_split_into_enters(self):
        self.enter_raw()
        self.rig.press(f"{ESC}[200~a\nb{ESC}[201~")
        self.assertEqual(self.rig.sender.sent, [])
        self.assertEqual(self.rig.ctl.mode, "raw")
        self.assertIn("çok satırlı", self.rig.bar_text(160))

    def test_not_live_drops_the_keys_and_shows_why_in_the_red_bar(self):
        self.enter_raw()
        self.rig.viewer.apply_failure("x")
        self.rig.press("abc")
        self.assertEqual(self.rig.sender.sent, [])
        text, style = self.rig.bar(160)
        self.assertEqual(style, watch.STYLE_RAW)
        self.assertIn("HAM GEÇİŞ", text)
        self.assertIn("gönderilmedi", text)
        self.assertEqual(self.rig.ctl.mode, "raw")

    def test_large_data_is_split_to_the_panels_per_request_limit(self):
        self.enter_raw()
        with mock.patch.object(watch.InputController, "RAW_CHUNK_CHARS", 5):
            self.rig.press(f"{ESC}[200~{'x' * 12}{ESC}[201~")
        self.assertEqual([len(p) for _, p in self.rig.sender.sent], [5, 5, 2])
        self.assertEqual("".join(p for _, p in self.rig.sender.sent), "x" * 12)

    def test_the_chunk_size_is_within_what_the_panel_accepts(self):
        from claudeops.commands import web
        self.assertLessEqual(watch.InputController.RAW_CHUNK_CHARS, web.MAX_TERM_RAW_CHARS)

    def test_raw_successes_are_silent_but_failures_show(self):
        self.enter_raw()
        self.rig.press("a")
        self.rig.sender.finish(1)
        self.rig.press("")
        self.assertNotIn("gönderildi", self.rig.bar_text(160))
        self.rig.press("b")
        self.rig.sender.finish(2, ok=False, err="oturum yok")
        self.rig.press("")
        self.assertIn("oturum yok", self.rig.bar_text(160))

    def test_shutdown_while_raw_restores_the_terminal_and_closes_the_sender(self):
        self.enter_raw()
        self.rig.ctl.shutdown()
        self.assertEqual(self.rig.keys.passthrough, [True, False])
        self.assertTrue(self.rig.sender.closed)

    def test_shutdown_outside_raw_leaves_the_terminal_alone(self):
        self.rig.ctl.shutdown()
        self.assertEqual(self.rig.keys.passthrough, [])
        self.assertTrue(self.rig.sender.closed)

    def test_a_pending_batch_is_flushed_on_shutdown(self):
        self.enter_raw()
        self.rig.ctl._raw_buf.append("zz")   # bu turda biriken ama henüz yollanmamış tuş
        self.rig.ctl.shutdown()
        self.assertEqual(self.rig.sender.sent, [("raw", "zz")])

    def test_without_a_keys_object_nothing_crashes(self):
        rig = Rig()
        rig.ctl._keys = None
        rig.press("R", "\n", "a", "\x1d")
        self.assertEqual(rig.sender.sent, [("raw", "a")])


# ── normal kip ve döngü ─────────────────────────────────────────────────────────────────────

class NormalModeTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()

    def test_q_and_capital_q_quit(self):
        self.assertTrue(self.rig.press("q"))
        self.assertTrue(Rig().press("Q"))

    def test_x_hides_the_popup_without_quitting(self):
        self.rig.viewer.apply_failure("ConnectionRefusedError")
        self.assertFalse(self.rig.press("x"))
        self.assertTrue(self.rig.viewer.popup_hidden)

    def test_x_while_everything_is_fine_does_not_suppress_the_next_outage(self):
        self.rig.press("x")
        self.assertFalse(self.rig.viewer.popup_hidden)

    def test_other_keys_do_nothing(self):
        self.assertFalse(self.rig.press("a", "r", "1", "\n", ESC, f"{ESC}[A"))
        self.assertEqual(self.rig.ctl.mode, "normal")
        self.assertEqual(self.rig.sender.sent, [])

    def test_a_q_inside_an_escape_sequence_or_alt_combination_does_not_quit(self):
        self.assertFalse(self.rig.press(f"{ESC}OQ", f"{ESC}q"))

    def test_pasted_text_never_acts_as_commands(self):
        self.assertFalse(self.rig.press(f"{ESC}[200~qqqxikR{ESC}[201~"))
        self.assertEqual(self.rig.ctl.mode, "normal")
        self.assertEqual(self.rig.sender.sent, [])

    def test_a_single_character_paste_is_not_a_command_either(self):
        # `Paste("q") == "q"`: koruma yalnız tür denetimiyle çalışır, metin eşitliği yetmez.
        for ch in "qQxXiIkKR":
            rig = Rig()
            self.assertFalse(rig.press(f"{ESC}[200~{ch}{ESC}[201~"), ch)
            self.assertEqual(rig.ctl.mode, "normal", ch)

    def test_commands_work_when_they_arrive_together(self):
        self.rig.press("ik")   # i yazı satırını açar; k artık metin
        self.assertEqual(self.rig.ctl.buf, "k")

    def test_quit_ignores_whatever_follows_it_in_the_same_read(self):
        self.assertTrue(self.rig.press("qia\r"))
        self.assertEqual(self.rig.sender.sent, [])

    def test_uppercase_i_and_k_work_too(self):
        self.rig.press("I")
        self.assertEqual(self.rig.ctl.mode, "compose")
        rig = Rig()
        rig.press("K")
        self.assertEqual(rig.ctl.mode, "keys")

    def test_normal_bar_is_the_status_bar(self):
        self.assertIsNone(self.rig.bar())


class TickTests(unittest.TestCase):
    def test_slow_when_idle_fast_in_every_input_mode(self):
        rig = Rig()
        self.assertEqual(rig.ctl.tick_seconds(), watch.TICK_SECONDS)
        for keys, mode in (("i", "compose"), (ESC, "normal"), ("k", "keys"), ("k", "normal"),
                           ("R", "rawask"), ("\n", "raw")):
            rig.press(keys)
            self.assertEqual(rig.ctl.mode, mode, keys)
            want = watch.TICK_SECONDS if mode == "normal" else watch.INPUT_TICK_SECONDS
            self.assertEqual(rig.ctl.tick_seconds(), want, mode)

    def test_input_tick_is_much_faster_than_the_idle_tick(self):
        self.assertLessEqual(watch.INPUT_TICK_SECONDS * 4, watch.TICK_SECONDS)

    def test_transports_follow_a_callable_tick(self):
        self.assertEqual(watch._tick_seconds(0.25), 0.25)
        values = iter([0.05, 0.25])
        fn = lambda: next(values)
        self.assertEqual((watch._tick_seconds(fn), watch._tick_seconds(fn)), (0.05, 0.25))

    def test_ws_transport_reads_the_tick_on_every_wait(self):
        timeouts = []

        class RecordingWS:
            def recv(self, timeout=None):
                timeouts.append(timeout)
                raise TimeoutError("timed out")

            def close(self):
                pass

        ticks = iter([0.25, 0.05, 0.05, 0.25])
        ws = watch.WsTransport(1, "yuhem", "s1", connect=lambda url, **kw: RecordingWS(),
                               read_token=lambda: "tok", clock=Clock())
        gen = ws.frames(threading.Event(), lambda: next(ticks))
        for _ in range(4):
            self.assertIsNone(next(gen))
        gen.close()
        self.assertEqual(timeouts, [0.25, 0.05, 0.05, 0.25])

    def test_rest_transport_reads_the_tick_between_polls(self):
        slept = []
        clock = Clock()

        def sleep(seconds):
            slept.append(seconds)
            clock.now += seconds

        class Resp:
            def read(self):
                return json.dumps(good()).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        ticks = iter([0.05, 0.25, 0.05])
        rest = watch.RestTransport(1, "yuhem", "s1", read_token=lambda: "tok", urlopen=lambda req, timeout=None: Resp(),
                                   clock=clock, sleep=sleep)
        gen = rest.frames(threading.Event(), lambda: next(ticks))
        self.assertIsNotNone(next(gen))      # kare
        for _ in range(3):
            self.assertIsNone(next(gen))     # sessiz tick'ler
        gen.close()
        self.assertEqual(slept, [0.05, 0.25, 0.05])


class ViewerIntegrationTests(unittest.TestCase):
    def test_the_overlay_replaces_the_status_bar_and_gives_it_back(self):
        rig = Rig()
        rig.viewer.render()
        self.assertIn("canlı", rig.out.getvalue())
        rig.out.truncate(0), rig.out.seek(0)
        rig.press("ihi")
        rig.viewer.render()
        drawn = rig.out.getvalue()
        self.assertIn("✎ ▸ hi█", drawn)
        self.assertNotIn("canlı", drawn)
        rig.out.truncate(0), rig.out.seek(0)
        rig.press(ESC)
        rig.viewer.render()
        self.assertIn("canlı", rig.out.getvalue())

    def test_typing_redraws_only_the_bar_not_the_body(self):
        rig = Rig()
        rig.viewer.render()
        rig.press("i")
        rig.viewer.render()
        rig.out.truncate(0), rig.out.seek(0)
        rig.press("x")
        rig.viewer.render()
        drawn = rig.out.getvalue()
        self.assertIn("✎ ▸ x█", drawn)
        self.assertNotIn("v1", drawn)

    def test_the_key_hint_is_appended_to_the_normal_bar(self):
        rig = Rig()
        rig.viewer.hint = watch.INPUT_HINT
        text, _ = rig.viewer.status()
        self.assertTrue(text.endswith(watch.INPUT_HINT))

    def test_no_hint_by_default(self):
        rig = Rig()
        text, _ = rig.viewer.status()
        self.assertNotIn("yaz", text)

    def test_an_overlay_returning_none_keeps_the_status_bar(self):
        rig = Rig()
        rig.viewer.overlay = lambda cols: None
        rig.viewer.render()
        self.assertIn("canlı", rig.out.getvalue())


class ScreenPasteTests(unittest.TestCase):
    def test_bracketed_paste_is_requested_and_released_only_when_asked(self):
        out = io.StringIO()
        screen = watch.Screen(out, title="t", size_fn=lambda: (80, 24), bracketed_paste=True)
        screen.enter()
        self.assertIn(f"{ESC}[?2004h", out.getvalue())
        out.truncate(0), out.seek(0)
        screen.leave()
        self.assertIn(f"{ESC}[?2004l", out.getvalue())

    def test_read_only_viewers_do_not_touch_the_mode(self):
        out = io.StringIO()
        screen = watch.Screen(out, title="t", size_fn=lambda: (80, 24))
        screen.enter()
        screen.leave()
        self.assertNotIn("2004", out.getvalue())


class Script:
    """Sahte taşıyıcı: öğeler kare (dict), None (sessiz tick), istisna ya da çağrılabilir (yan etki). `frames`'e
    verilen `tick`i kaydeder."""

    name = "ws"

    def __init__(self, items):
        self.items = list(items)
        self.ticks = []

    def frames(self, stop, tick):
        self.ticks.append(tick)
        for item in self.items:
            if isinstance(item, BaseException):
                raise item
            if callable(item):
                item()
                continue
            yield item
        stop.set()


class ScriptedKeys:
    """`poll()` her çağrıda sıradaki parçayı verir (boşsa "")."""

    def __init__(self, *chunks):
        self.chunks = list(chunks)

    def poll(self):
        return self.chunks.pop(0) if self.chunks else ""


class WatchLoopInputTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(live=False)
        self.stop = threading.Event()
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.rig.clock.now += seconds

    def run_loop(self, ws, keys, mode="ws"):
        rest = Script([])
        rest.name = "rest"
        watch.watch_loop(self.rig.viewer, ws, rest, mode=mode, stop=self.stop, keys=keys, controller=self.rig.ctl,
                         backoff=watch.Backoff(rand=lambda: 1.0), clock=self.rig.clock, sleep=self.sleep)

    def test_a_typed_message_goes_out_through_the_loop_and_q_ends_it(self):
        ws = Script([good(), None, None, None, None, None, None, None, None])
        self.run_loop(ws, ScriptedKeys("", "i", "mer", "haba", "\r", "", "q"))
        self.assertEqual(self.rig.sender.sent, [("text", "merhaba")])
        self.assertTrue(self.stop.is_set())
        drawn = self.rig.out.getvalue()
        self.assertIn("✎ ▸ merhaba█", drawn)

    def test_the_transport_gets_a_tick_that_follows_the_mode(self):
        seen = []
        ws = Script([good(), None])
        ws.items.append(lambda: seen.append(watch._tick_seconds(ws.ticks[0])))   # 'i' işlendikten sonra
        ws.items.append(None)
        self.run_loop(ws, ScriptedKeys("", "i"))
        self.assertTrue(callable(ws.ticks[0]))
        self.assertEqual(seen, [watch.INPUT_TICK_SECONDS])

    def test_keys_are_served_while_the_connection_is_down_but_nothing_is_sent(self):
        ws = Script([watch.TransportError("ConnectionRefusedError")])
        keys = ScriptedKeys("", "i", "selam", "\r", ESC, "q")
        self.run_loop(ws, keys)
        self.assertEqual(self.rig.sender.sent, [])
        self.assertTrue(self.stop.is_set())

    def test_the_reconnect_wait_wakes_at_the_input_tick_while_a_mode_is_open(self):
        ws = Script([watch.TransportError("ConnectionRefusedError")])
        self.run_loop(ws, ScriptedKeys("", "i", "", "", "", ESC, "q"))
        self.assertIn(watch.INPUT_TICK_SECONDS, self.sleeps)

    def test_without_a_controller_the_old_behaviour_is_unchanged(self):
        ws = Script([good(), None, None, None])
        rest = Script([])
        rest.name = "rest"
        screen, out = make_screen()
        viewer = watch.Viewer("yuhem", "s1", screen, clock=self.rig.clock)
        watch.watch_loop(viewer, ws, rest, mode="ws", stop=self.stop, keys=ScriptedKeys("", "i", "q"),
                         backoff=watch.Backoff(rand=lambda: 1.0), clock=self.rig.clock, sleep=self.sleep)
        self.assertEqual(ws.ticks, [watch.TICK_SECONDS])
        self.assertTrue(self.stop.is_set())
        self.assertNotIn("✎", out.getvalue())


class RegisterTests(unittest.TestCase):
    def test_read_only_flag(self):
        from claudeops import cli
        parser = cli.build_parser()
        self.assertTrue(parser.parse_args(["watch", "x", "--read-only"]).read_only)
        self.assertFalse(parser.parse_args(["watch", "x"]).read_only)


# ── uçtan uca: gerçek görüntüleyici süreci, kontrol terminali olan bir pty, sahte panel ───────

class ViewerPanel:
    """Sahte panel: GET /api/term/output sabit bir kare verir, POST'ları kaydeder."""

    def __init__(self, token="tok"):
        self.token = token
        self.posts = []
        panel = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, status, obj):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.headers.get("Authorization") != f"Bearer {panel.token}":
                    return self._reply(401, {"ok": False})
                self._reply(200, good("merhaba\ndunya", cols=40, rows=2))

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.headers.get("Authorization") != f"Bearer {panel.token}":
                    return self._reply(401, {"ok": False})
                panel.posts.append((self.path, body))
                self._reply(200, {"ok": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def raw_data(self):
        return "".join(b["data"] for p, b in list(self.posts) if p == "/api/term/raw")


# pty'nin kontrol terminali olması için: yeni oturum aç, stdin'i kontrol terminali yap, görüntüleyiciye geç.
# (Böylece Ctrl-C gerçekten SIGINT üretir; ISIG'in ham geçişte kapanıp sonra geri açıldığı görülebilir.)
_LAUNCH = ("import os, sys, fcntl, termios; os.setsid(); fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
           "os.execv(sys.executable, [sys.executable, '-m', 'claudeops', 'watch'] + sys.argv[1:])")


@unittest.skipIf(pty is None, "pty yok")
class ViewerProcessTests(unittest.TestCase):
    def setUp(self):
        self.panel = ViewerPanel()
        self.addCleanup(self.panel.close)
        self.workdir = tempfile.mkdtemp(prefix="cops_watch_input_")
        self.addCleanup(shutil.rmtree, self.workdir, True)
        with open(os.path.join(self.workdir, "web.token"), "w") as f:
            f.write("tok")
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 8, 70, 0, 0))
        env = dict(os.environ, CLAUDEOPS_DIR=self.workdir, TERM="xterm-256color", PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(
            [sys.executable, "-c", _LAUNCH, "local:x", "--port", str(self.panel.port), "--transport", "rest",
             "--no-resize"],
            stdin=slave, stdout=slave, stderr=slave, cwd=PY_DIR, env=env, close_fds=True)
        os.close(slave)
        self.buf = bytearray()
        self.lock = threading.Lock()
        threading.Thread(target=self.drain, daemon=True).start()
        self.addCleanup(self.cleanup)

    def drain(self):
        while True:
            try:
                data = os.read(self.master, 4096)
            except OSError:
                return
            if not data:
                return
            with self.lock:
                self.buf += data

    def cleanup(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(5)
        with contextlib.suppress(OSError):
            os.close(self.master)

    def screen_text(self):
        with self.lock:
            return bytes(self.buf).decode("utf-8", "replace")

    def mark(self):
        return len(self.screen_text())

    def wait_screen(self, needle, since=0, timeout=15.0):
        end = time.time() + timeout
        while time.time() < end:
            if needle in self.screen_text()[since:]:
                return True
            if self.proc.poll() is not None:
                break
            time.sleep(0.02)
        self.fail(f"ekranda {needle!r} görünmedi; son çıktı: {self.screen_text()[-400:]!r}")

    def wait_posts(self, count, timeout=10.0):
        end = time.time() + timeout
        while len(self.panel.posts) < count and time.time() < end:
            time.sleep(0.02)
        self.assertGreaterEqual(len(self.panel.posts), count, self.panel.posts)

    def send(self, data):
        os.write(self.master, data if isinstance(data, bytes) else data.encode())

    def test_full_session_compose_short_key_raw_and_exit(self):
        self.wait_screen("canlı")
        self.wait_screen("i yaz · k tuş · R ham")
        time.sleep(0.4)
        self.assertEqual(self.panel.posts, [], "hiçbir tuş kendiliğinden gitmemeli")

        # yazı satırı
        m = self.mark()
        self.send("i")
        self.wait_screen("✎", since=m)
        self.send("merhaba şğ")
        self.wait_screen("merhaba şğ█", since=m)
        self.assertEqual(self.panel.posts, [], "Enter'dan önce hiçbir şey gitmemeli")
        self.send("\r")
        self.wait_posts(1)
        self.assertEqual(self.panel.posts[0], (
            "/api/term/input", {"name": "x", "host": "local", "text": "merhaba şğ", "lang": "en"}))

        # kısa tuş
        m = self.mark()
        self.send("k")
        self.wait_screen("kısa tuş", since=m)
        self.send("\x1b[B")
        self.wait_posts(2)
        self.assertEqual(self.panel.posts[1], (
            "/api/term/key", {"name": "x", "host": "local", "key": "Down", "lang": "en"}))

        # ham geçiş: onay, sonra Enter \r olarak ve Ctrl-C öldürmeden gider
        m = self.mark()
        self.send("R")
        self.wait_screen("HAM GEÇİŞ açılsın mı", since=m)
        self.send("\r")
        self.wait_screen("her tuş oturuma gider", since=m)
        time.sleep(0.2)
        self.send("ls\r")
        self.send("\x03")
        end = time.time() + 10
        while self.panel.raw_data() != "ls\r\x03" and time.time() < end:
            time.sleep(0.02)
        self.assertEqual(self.panel.raw_data(), "ls\r\x03")
        self.assertIsNone(self.proc.poll(), "ham geçişte Ctrl-C görüntüleyiciyi kapatmamalı")

        # Ctrl-] ile çık; sonra Ctrl-C yeniden öldürür (ISIG geri geldi)
        m = self.mark()
        self.send("\x1d")
        self.wait_screen("ham geçiş kapandı", since=m)
        time.sleep(0.2)
        self.send("\x03")
        self.assertEqual(self.proc.wait(10), 0)
        self.assertEqual(self.panel.raw_data(), "ls\r\x03", "çıkıştan sonra hiçbir şey gitmemeli")

    def test_q_quits_and_a_pasted_q_does_not(self):
        self.wait_screen("canlı")
        self.send("\x1b[200~qqq\x1b[201~")
        time.sleep(0.5)
        self.assertIsNone(self.proc.poll(), "yapıştırılan q çıkış sayılmamalı")
        self.send("q")
        self.assertEqual(self.proc.wait(10), 0)
        self.assertEqual(self.panel.posts, [])

    def test_the_terminal_is_given_back_clean(self):
        self.wait_screen("canlı")
        self.send("q")
        self.proc.wait(10)
        time.sleep(0.2)
        out = self.screen_text()
        self.assertIn(f"{ESC}[?2004h", out)
        self.assertTrue(out.rstrip().endswith(f"{ESC}[?1049l"), out[-120:])
        self.assertLess(out.rindex(f"{ESC}[?2004l"), out.rindex(f"{ESC}[?1049l"))


class ReadOnlyProcessTests(unittest.TestCase):
    """`--read-only`: hiçbir tuş oturuma gitmez, bracketed paste istenmez."""

    @unittest.skipIf(pty is None, "pty yok")
    def test_read_only_sends_nothing(self):
        panel = ViewerPanel()
        self.addCleanup(panel.close)
        workdir = tempfile.mkdtemp(prefix="cops_watch_ro_")
        self.addCleanup(shutil.rmtree, workdir, True)
        with open(os.path.join(workdir, "web.token"), "w") as f:
            f.write("tok")
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 8, 70, 0, 0))
        env = dict(os.environ, CLAUDEOPS_DIR=workdir, TERM="xterm-256color", PYTHONUNBUFFERED="1")
        proc = subprocess.Popen(
            [sys.executable, "-c", _LAUNCH, "local:x", "--port", str(panel.port), "--transport", "rest",
             "--no-resize", "--read-only"],
            stdin=slave, stdout=slave, stderr=slave, cwd=PY_DIR, env=env, close_fds=True)
        os.close(slave)
        self.addCleanup(lambda: (proc.poll() is None and proc.kill(), proc.wait(5), os.close(master)))
        buf = bytearray()

        def drain():
            while True:
                try:
                    data = os.read(master, 4096)
                except OSError:
                    return
                if not data:
                    return
                buf.extend(data)

        threading.Thread(target=drain, daemon=True).start()
        end = time.time() + 15
        while b"canl" not in bytes(buf) and time.time() < end:
            time.sleep(0.02)
        self.assertIn("canlı", bytes(buf).decode("utf-8", "replace"))
        self.assertNotIn("i yaz", bytes(buf).decode("utf-8", "replace"))
        os.write(master, b"i")
        os.write(master, b"selam\r")
        os.write(master, b"k\n")
        os.write(master, b"R\r")
        os.write(master, b"ab\r")
        time.sleep(0.6)
        self.assertEqual(panel.posts, [])
        self.assertNotIn("✎", bytes(buf).decode("utf-8", "replace"))
        self.assertNotIn("?2004h", bytes(buf).decode("utf-8", "replace"))
        os.write(master, b"q")
        self.assertEqual(proc.wait(10), 0)


if __name__ == "__main__":
    unittest.main()

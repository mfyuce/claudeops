"""`py/cops watch` (commands/watch.py) testleri (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_watch.py -v

Ağ yalnız 127.0.0.1'e (sahte panel: stdlib HTTP sunucusu, `websockets` varsa gerçek bir WS sunucusu);
gerçek panele, tmux'a, terminale DOKUNMAZ. Zaman sahte saat/uykuyla ilerler, hiçbir test gerçekten
beklemez. Gerçek TTY/alt-ekran davranışı ayrıca elle (tmux içinde) doğrulandı, bkz. DONE.md.
"""
import contextlib
import io
import json
import logging
import os
import queue
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import watch  # noqa: E402

ESC = "\x1b"


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


def make_screen(size=(80, 24)):
    out = io.StringIO()
    dims = {"size": size}
    screen = watch.Screen(out, title="yuhem:s1", size_fn=lambda: dims["size"])
    return screen, out, dims


# ── hedef, sınıflama ──────────────────────────────────────────────────────────────────────

class ParseTargetTests(unittest.TestCase):
    def test_host_and_name(self):
        self.assertEqual(watch.parse_target("ulak_31:rustrino20261009"), ("ulak_31", "rustrino20261009"))

    def test_bare_name_is_local(self):
        self.assertEqual(watch.parse_target("cops20261007"), ("local", "cops20261007"))

    def test_explicit_local(self):
        self.assertEqual(watch.parse_target("local:x"), ("local", "x"))

    def test_only_first_colon_splits(self):
        self.assertEqual(watch.parse_target("h:a:b"), ("h", "a:b"))

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertEqual(watch.parse_target("  h:n  "), ("h", "n"))

    def test_bad_targets(self):
        for bad in ("", ":", "h:", ":n", "a b", "h:a b", "h:a\tb", "h:a\x1bb"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    watch.parse_target(bad)


class ClassifyFrameTests(unittest.TestCase):
    def test_live(self):
        self.assertEqual(watch.classify_frame(good()), ("live", ""))

    def test_ok_without_text_is_reconnecting(self):
        self.assertEqual(watch.classify_frame({"ok": True})[0], "reconnecting")

    def test_not_a_dict(self):
        for bad in (None, "x", [], 3):
            self.assertEqual(watch.classify_frame(bad)[0], "reconnecting")

    def test_host_unreachable_is_reconnecting(self):
        state, detail = watch.classify_frame({"ok": False, "error": "yuhem unreachable: timed out"})
        self.assertEqual((state, detail), ("reconnecting", "yuhem unreachable: timed out"))

    def test_relay_messages_are_reconnecting(self):
        for msg in ("relay: henüz veri gelmedi", "relay: bağlantı koptu, yeniden deneniyor"):
            self.assertEqual(watch.classify_frame({"ok": False, "error": msg})[0], "reconnecting")

    def test_not_running_is_waiting(self):
        self.assertEqual(watch.classify_frame({"ok": False, "error": "s1: not running"}),
                         ("waiting", "s1: not running"))

    def test_unknown_host_and_gone_session_are_waiting(self):
        for msg in ("unknown host: nope", "s1: tmux session no longer exists (may have closed)"):
            self.assertEqual(watch.classify_frame({"ok": False, "error": msg})[0], "waiting")

    def test_error_without_text(self):
        self.assertEqual(watch.classify_frame({"ok": False})[0], "waiting")


# ── genişlik ve kırpma ─────────────────────────────────────────────────────────────────────

class WidthTests(unittest.TestCase):
    def test_char_width(self):
        self.assertEqual(watch.char_width("a"), 1)
        self.assertEqual(watch.char_width("ş"), 1)
        self.assertEqual(watch.char_width("界"), 2)
        self.assertEqual(watch.char_width("́"), 0)   # birleşik vurgu
        self.assertEqual(watch.char_width("\x07"), 0)

    def test_display_width_ignores_escape_sequences(self):
        s = f"{ESC}[1;31mhi{ESC}[0m {ESC}]0;title\x07界"
        self.assertEqual(watch.display_width(s), 2 + 1 + 2)

    def test_truncate_keeps_short_lines_intact(self):
        s = f"{ESC}[31mred{ESC}[0m"
        self.assertEqual(watch.truncate_ansi(s, 10), s)

    def test_truncate_cuts_visible_width_and_keeps_leading_escapes(self):
        s = f"{ESC}[31mabcdef{ESC}[0m"
        out = watch.truncate_ansi(s, 3)
        self.assertEqual(out, f"{ESC}[31mabc")
        self.assertEqual(watch.display_width(out), 3)

    def test_truncate_does_not_split_a_wide_char(self):
        self.assertEqual(watch.truncate_ansi("a界b", 2), "a")     # 界 sığmaz
        self.assertEqual(watch.truncate_ansi("a界b", 3), "a界")

    def test_truncate_zero_width(self):
        self.assertEqual(watch.truncate_ansi("abc", 0), "")

    def test_truncate_keeps_combining_marks_with_their_base(self):
        self.assertEqual(watch.truncate_ansi("éx", 1), "é")

    def test_fit_lines_keeps_the_bottom_rows(self):
        self.assertEqual(watch.fit_lines("a\nb\nc\nd", 80, 2), ["c", "d"])

    def test_fit_lines_drops_the_capture_terminator_of_a_full_frame(self):
        self.assertEqual(watch.fit_lines("a\nb\n", 80, 5), ["a", "b"])

    def test_fit_lines_keeps_the_blank_last_row_of_a_lite_frame(self):
        # lite metin tam `rows` satırdır; son pane satırı boşsa "\\n" ile biter ve o boş satır SAYILIR
        self.assertEqual(watch.fit_lines("a\nb\n", 80, 5, lite=True), ["a", "b", ""])
        self.assertEqual(watch.fit_lines("a\nb", 80, 5, lite=True), ["a", "b"])

    def test_frame_rows_matches_the_servers_viewport_text(self):
        from claudeops.commands import web_term_lite
        capture = "old\nv1\n\n\n"          # 3 görünür satır: v1 + iki boş (tam capture, scrollback'li)
        lite_text = web_term_lite.viewport_text(capture, 3)
        self.assertEqual(watch.frame_rows(lite_text, True), ["v1", "", ""])
        self.assertEqual(watch.frame_rows(capture, False), ["old", "v1", "", ""])

    def test_fit_lines_truncates_columns(self):
        self.assertEqual(watch.fit_lines("abcdef\nxy", 3, 5), ["abc", "xy"])

    def test_fit_lines_zero_height(self):
        self.assertEqual(watch.fit_lines("a\nb", 80, 0), [])

    def test_fmt_age(self):
        self.assertEqual([watch.fmt_age(x) for x in (-5, 0, 12.9, 59, 60, 185, 3600, 7300)],
                         ["0 sn", "0 sn", "12 sn", "59 sn", "1 dk", "3 dk", "1 sa", "2 sa"])


class BuildTests(unittest.TestCase):
    def test_body_uses_absolute_positions_and_no_newlines(self):
        out = watch.build_body(["a", "b"], 3)
        self.assertNotIn("\n", out)
        self.assertEqual(out, f"{ESC}[1;1Ha{ESC}[0m{ESC}[K{ESC}[2;1Hb{ESC}[0m{ESC}[K{ESC}[3;1H{ESC}[0m{ESC}[K")

    def test_body_with_no_rows(self):
        self.assertEqual(watch.build_body(["a"], 0), "")
        self.assertEqual(watch.build_body(["a"], -3), "")

    def test_status_is_padded_to_the_full_width(self):
        out = watch.build_status(" ● canlı", watch.STYLE_LIVE, 20, 24)
        self.assertTrue(out.startswith(f"{ESC}[24;1H{watch.STYLE_LIVE}"))
        self.assertEqual(watch.display_width(out), 20)

    def test_status_is_truncated_when_too_wide(self):
        out = watch.build_status(" x" * 40, watch.STYLE_LIVE, 10, 5)
        self.assertEqual(watch.display_width(out), 10)


class BackoffTests(unittest.TestCase):
    def test_exponential_with_cap(self):
        b = watch.Backoff(rand=lambda: 1.0)   # jitter üst sınırı: %100
        self.assertEqual([b.next() for _ in range(7)], [1.0, 2.0, 4.0, 8.0, 15.0, 15.0, 15.0])

    def test_jitter_only_goes_down(self):
        b = watch.Backoff(rand=lambda: 0.0)   # jitter alt sınırı: %80
        self.assertEqual([round(b.next(), 3) for _ in range(5)], [0.8, 1.6, 3.2, 6.4, 12.0])

    def test_never_exceeds_cap(self):
        b = watch.Backoff()
        self.assertTrue(all(b.next() <= watch.BACKOFF_CAP_SECONDS for _ in range(50)))

    def test_reset(self):
        b = watch.Backoff(rand=lambda: 1.0)
        b.next(), b.next(), b.next()
        b.reset()
        self.assertEqual(b.next(), 1.0)


class TokenTests(unittest.TestCase):
    def test_reads_and_strips(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "web.token")
            with open(p, "w") as f:
                f.write("abc123\n")
            self.assertEqual(watch.read_token(p), "abc123")

    def test_missing_and_empty_are_auth_errors(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(watch.TransportError) as cm:
                watch.read_token(os.path.join(d, "nope"))
            self.assertTrue(cm.exception.auth)
            p = os.path.join(d, "empty")
            open(p, "w").close()
            with self.assertRaises(watch.TransportError) as cm:
                watch.read_token(p)
            self.assertTrue(cm.exception.auth)


# ── ekran / görüntüleyici ──────────────────────────────────────────────────────────────────

class ScreenTests(unittest.TestCase):
    def test_enter_and_leave(self):
        screen, out, _ = make_screen()
        screen.enter()
        entered = out.getvalue()
        for seq in ("?1049h", "?25l", "?7l", f"{ESC}]0;yuhem:s1\x07"):
            self.assertIn(seq, entered)
        out.truncate(0), out.seek(0)
        screen.leave()
        left = out.getvalue()
        for seq in ("?7h", "?25h", "?1049l"):
            self.assertIn(seq, left)

    def test_title_has_no_control_characters(self):
        screen = watch.Screen(io.StringIO(), title="a\x1bb\x07c", size_fn=lambda: (80, 24))
        self.assertEqual(screen.title_seq(), f"{ESC}]0;abc\x07")

    def test_write_failure_marks_the_screen_dead_instead_of_raising(self):
        class Broken:
            def write(self, _):
                raise OSError(5, "I/O error")

            def flush(self):
                pass

        screen = watch.Screen(Broken(), title="t", size_fn=lambda: (80, 24))
        screen.write("x")
        self.assertTrue(screen.dead)
        screen.write("y")  # ölü ekrana yazma sessizce atlanır


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.screen, self.out, self.dims = make_screen((80, 5))   # 4 gövde satırı + çubuk
        self.viewer = watch.Viewer("yuhem", "s1", self.screen, clock=self.clock)
        self.viewer.transport_name = "ws"

    def drawn(self):
        data = self.out.getvalue()
        self.out.truncate(0), self.out.seek(0)
        return data

    def test_first_render_draws_body_status_and_title(self):
        self.viewer.apply_frame(good("v1\nv2\nv3\nv4", cols=80, rows=4))
        self.viewer.render()
        data = self.drawn()
        self.assertIn(f"{ESC}[1;1Hv1", data)
        self.assertIn(f"{ESC}[4;1Hv4", data)
        self.assertIn("canlı", data)
        self.assertIn(f"{ESC}]0;yuhem:s1\x07", data)

    def test_unchanged_state_draws_nothing(self):
        self.viewer.apply_frame(good())
        self.viewer.render()
        self.drawn()
        self.viewer.apply_frame(good())   # aynı kare (sunucu heartbeat'i)
        self.viewer.render()
        self.assertEqual(self.drawn(), "")

    def test_new_frame_redraws_the_body_only(self):
        self.viewer.apply_frame(good("a\nb\nc"))
        self.viewer.render()
        self.drawn()
        self.viewer.apply_frame(good("a\nb\nCHANGED"))
        self.viewer.render()
        data = self.drawn()
        self.assertIn("CHANGED", data)
        self.assertNotIn("canlı", data)   # çubuk metni değişmedi

    def test_failure_keeps_the_last_body_and_shows_the_age_in_the_status(self):
        self.viewer.apply_frame(good("keep\nme\nhere"))
        self.viewer.render()
        self.drawn()
        self.clock.now += 12
        self.viewer.apply_failure("ConnectionRefusedError")
        self.viewer.render()
        data = self.drawn()
        self.assertNotIn("keep", data)           # gövdeye dokunulmadı
        self.assertIn("yeniden bağlanıyor", data)
        self.assertIn("son güncelleme 12 sn önce", data)
        self.assertIn("ConnectionRefusedError", data)

    def test_age_ticks_while_disconnected(self):
        self.viewer.apply_frame(good())
        self.viewer.apply_failure("x")
        self.viewer.render()
        self.drawn()
        self.clock.now += 1
        self.viewer.render()
        self.assertIn("son güncelleme 1 sn önce", self.drawn())

    def test_quiet_ticks_keep_the_content_fresh_so_the_age_counts_from_the_disconnect(self):
        self.viewer.apply_frame(good())
        self.clock.now += 40                 # sessiz pane: kare gelmedi ama bağlantı sağlıklı
        self.viewer.confirm_fresh()
        self.clock.now += 1
        self.viewer.apply_failure("dropped")
        self.clock.now += 4
        self.viewer.render()
        data = self.drawn()
        self.assertIn("son güncelleme 5 sn önce", data)   # 45 değil: son DOĞRULAMA 40. sn'ydi
        self.assertNotIn("45 sn", data)

    def test_quiet_ticks_do_not_refresh_while_waiting_or_reconnecting(self):
        self.viewer.apply_frame(good())
        self.viewer.apply_frame({"ok": False, "error": "s1: not running"})
        self.clock.now += 30
        self.viewer.confirm_fresh()          # bekleme sırasında içerik artık güncel değil
        self.viewer.render()
        self.assertIn("son güncelleme 30 sn önce", self.drawn())

    def test_retry_countdown_is_shown(self):
        self.viewer.apply_failure("refused")
        self.viewer.set_retry_in(3.2)
        self.viewer.render()
        self.assertIn("(4 sn)", self.drawn())

    def test_age_is_not_shown_while_live(self):
        self.viewer.apply_frame(good())
        self.clock.now += 40   # sessiz pane: WS yalnız değişince/30 sn'de bir yollar
        self.viewer.render()
        self.assertNotIn("son güncelleme", self.drawn())

    def test_waiting_state_shows_the_server_message_and_keeps_the_body(self):
        self.viewer.apply_frame(good("old\nscreen\nhere"))
        self.viewer.render()
        self.drawn()
        self.viewer.apply_frame({"ok": False, "error": "s1: not running"})
        self.viewer.render()
        data = self.drawn()
        self.assertIn("bekliyor", data)
        self.assertIn("s1: not running", data)
        self.assertNotIn("old", data)

    def test_severe_failure_uses_the_red_style(self):
        self.viewer.apply_failure("http 401", severe=True)
        self.viewer.render()
        self.assertIn(watch.STYLE_SEVERE, self.drawn())

    def test_recovery_clears_the_failure(self):
        self.viewer.apply_failure("boom", severe=True)
        self.viewer.apply_frame(good())
        self.assertEqual((self.viewer.state, self.viewer.detail, self.viewer.severe), ("live", "", False))

    def test_resize_is_requested_once_per_pane_size(self):
        self.viewer.apply_frame(good(cols=100, rows=30))
        self.viewer.render()
        self.assertEqual(self.drawn().count(f"{ESC}[8;31;100t"), 1)   # 30 satır + 1 çubuk, 100 sütun
        self.viewer.apply_frame(good("x\ny", cols=100, rows=30))
        self.viewer.render()
        self.assertNotIn("[8;", self.drawn())
        self.viewer.apply_frame(good("x\ny", cols=120, rows=40))
        self.viewer.render()
        self.assertIn(f"{ESC}[8;41;120t", self.drawn())

    def test_resize_can_be_disabled(self):
        viewer = watch.Viewer("yuhem", "s1", self.screen, resize=False, clock=self.clock)
        viewer.apply_frame(good(cols=100, rows=30))
        viewer.render()
        self.assertNotIn("[8;", self.drawn())

    def test_no_resize_without_a_known_pane_size(self):
        self.viewer.apply_frame(good(cols=None, rows=None))
        self.viewer.render()
        self.assertNotIn("[8;", self.drawn())

    def test_terminal_size_change_redraws_everything(self):
        self.viewer.apply_frame(good("a\nb\nc"))
        self.viewer.render()
        self.drawn()
        self.dims["size"] = (100, 8)
        self.viewer.render()
        data = self.drawn()
        self.assertIn(f"{ESC}[1;1Ha", data)          # gövde yeniden
        self.assertIn(f"{ESC}[8;1H", data)           # çubuk yeni son satırda
        self.assertIn(f"{ESC}]0;yuhem:s1\x07", data)  # başlık tazelendi

    def test_terminal_shorter_than_the_pane_shows_the_bottom_rows(self):
        self.viewer.apply_frame(good("l1\nl2\nl3\nl4\nl5\nl6", cols=80, rows=6))
        self.viewer.render()
        data = self.drawn()   # ekran 5 satır: 4 gövde + çubuk
        self.assertNotIn("l1", data)
        self.assertNotIn("l2", data)
        self.assertIn(f"{ESC}[1;1Hl3", data)
        self.assertIn(f"{ESC}[4;1Hl6", data)

    def test_blank_bottom_rows_of_a_lite_frame_count_when_cropping(self):
        # Pane 4 satır: l1, l2, l3, boş. Gövde 3 satır → dipten 3 = l2, l3, boş (l1 kırpılır).
        self.dims["size"] = (80, 4)    # 3 gövde satırı + çubuk
        self.viewer.apply_frame(good("l1\nl2\nl3\n", cols=80, rows=4))
        self.viewer.render()
        data = self.drawn()
        self.assertNotIn("l1", data)
        self.assertIn(f"{ESC}[1;1Hl2", data)
        self.assertIn(f"{ESC}[2;1Hl3", data)

    def test_terminal_narrower_than_the_pane_truncates_lines(self):
        self.dims["size"] = (6, 5)
        self.viewer.apply_frame(good("abcdefghij\nxyz", cols=10, rows=2))
        self.viewer.render()
        data = self.drawn()
        self.assertIn("abcdef", data)
        self.assertNotIn("abcdefg", data)

    def test_tall_terminal_blanks_the_rows_below_the_frame(self):
        self.dims["size"] = (80, 10)
        self.viewer.apply_frame(good("a\nb"))
        self.viewer.render()
        data = self.drawn()
        self.assertIn(f"{ESC}[9;1H{ESC}[0m{ESC}[K", data)   # 9. satır (son gövde satırı) boşaltıldı
        self.assertIn(f"{ESC}[10;1H", data)                  # çubuk 10. satırda

    def test_one_row_terminal_does_not_crash(self):
        self.dims["size"] = (80, 1)
        self.viewer.apply_frame(good())
        self.viewer.render()   # gövde 0 satır, yalnız çubuk

    def test_status_shows_pane_size_and_transport(self):
        self.viewer.apply_frame(good(cols=100, rows=30))
        text, _ = self.viewer.status()
        self.assertIn("100×30", text)
        self.assertTrue(text.rstrip().endswith("ws"))

    def test_control_characters_in_the_detail_never_reach_the_terminal(self):
        # hata metni panelden/uzak host'tan gelir; ESC dizisi (başlık/pano/imleç) çizime sızmamalı
        self.viewer.apply_failure("bad\x1b]0;pwn\x07 text\x1b[2J")
        self.viewer.render()
        data = self.drawn()
        self.assertNotIn(f"{ESC}]0;pwn", data)
        self.assertNotIn(f"{ESC}[2J", data)
        self.assertNotIn("\x07", data.replace(f"{ESC}]0;yuhem:s1\x07", ""))   # tek meşru BEL: başlık dizisi
        self.assertNotIn(ESC, self.viewer.detail)
        self.viewer.apply_frame({"ok": False, "error": "x\x1b[31m: not running"})
        self.assertNotIn(ESC, self.viewer.detail)


# ── sorun popup'ı ───────────────────────────────────────────────────────────────────────────

def plain(s):
    """Kaçış dizilerini atılmış görünür metin."""
    return watch._SEQ_RE.sub("", s)


class CleanTextTests(unittest.TestCase):
    def test_control_characters_become_spaces(self):
        self.assertEqual(watch.clean_text("a\x1b[31mb\nc\td\x07e"), "a [31mb c d e")

    def test_plain_text_is_unchanged_apart_from_trimming(self):
        self.assertEqual(watch.clean_text("  ConnectionRefusedError: [Errno 111]  "),
                         "ConnectionRefusedError: [Errno 111]")


class WrapTextTests(unittest.TestCase):
    def test_wraps_on_word_boundaries(self):
        self.assertEqual(watch.wrap_text("aaa bbb ccc ddd", 7, 5), ["aaa bbb", "ccc ddd"])

    def test_a_long_word_is_split_at_the_width(self):
        self.assertEqual(watch.wrap_text("abcdefghij", 4, 5), ["abcd", "efgh", "ij"])

    def test_text_beyond_max_lines_ends_with_an_ellipsis_within_the_width(self):
        lines = watch.wrap_text("one two three four five six seven", 9, 2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("…"))
        self.assertTrue(all(watch.display_width(ln) <= 9 for ln in lines))

    def test_empty_and_degenerate_inputs(self):
        self.assertEqual(watch.wrap_text("", 10, 2), [])
        self.assertEqual(watch.wrap_text("abc", 0, 2), [])
        self.assertEqual(watch.wrap_text("abc", 10, 0), [])

    def test_wide_characters_count_two_columns(self):
        lines = watch.wrap_text("日本語日本語", 6, 5)
        self.assertEqual(lines, ["日本語", "日本語"])


class DescribeProblemTests(unittest.TestCase):
    def title(self, state, detail, severe=False):
        return watch.describe_problem(state, detail, severe)[0]

    def test_the_keepalive_timeout_from_the_bug_report(self):
        detail = "ConnectionClosedError: sent 1011 (internal error) keepalive ping timeout; no close frame received"
        self.assertEqual(self.title("reconnecting", detail), "Panelle bağlantı koptu")

    def test_panel_down(self):
        for detail in ("ConnectionRefusedError: [Errno 111] Connection refused", "<urlopen error timed out>",
                       "ConnectionResetError: peer reset"):
            self.assertEqual(self.title("reconnecting", detail), "Panele ulaşılamıyor", detail)

    def test_silence_watchdog(self):
        self.assertEqual(self.title("reconnecting", "sunucudan 75 sn ses yok"), "Panelden haber gelmiyor")

    def test_host_level_problems_win_over_generic_timeouts(self):
        self.assertEqual(self.title("reconnecting", "yuhem unreachable: timed out"), "Host'a ulaşılamıyor")
        self.assertEqual(self.title("reconnecting", "relay: bağlantı koptu, yeniden deneniyor"),
                         "Uzak host bağlantısı koptu")

    def test_auth_is_its_own_title(self):
        self.assertEqual(self.title("reconnecting", "http 401: web.token ...", severe=True), "Yetki hatası")

    def test_unknown_errors_fall_back_to_a_generic_title(self):
        self.assertEqual(self.title("reconnecting", "something odd"), "Bağlantı sorunu")
        self.assertEqual(self.title("reconnecting", ""), "Bağlantı sorunu")

    def test_waiting_states(self):
        self.assertEqual(self.title("waiting", "s1: not running"), "Session çalışmıyor")
        self.assertEqual(self.title("waiting", "unknown host: nope"), "Host tanımsız")

    def test_every_hint_fits_next_to_the_hide_key_in_a_full_width_box(self):
        room = watch.POPUP_MAX_COLS - 8 - len(" · x: gizle")
        for state, detail, severe in (("waiting", "s1: not running", False), ("waiting", "unknown host: x", False),
                                      ("reconnecting", "x", True), ("reconnecting", "refused", False),
                                      ("reconnecting", "keepalive", False), ("reconnecting", "zzz", False)):
            hint = watch.describe_problem(state, detail, severe)[1]
            self.assertLessEqual(watch.display_width(hint), room, hint)


class PopupLayoutTests(unittest.TestCase):
    STYLE = watch.STYLE_RECONNECTING

    def layout(self, title="Panelle bağlantı koptu", detail="ConnectionClosedError: keepalive ping timeout",
               hint="Otomatik yeniden denenir", cols=100, body_rows=20):
        return watch.popup_layout(title, detail, hint, self.STYLE, cols, body_rows)

    def test_box_is_centered_and_every_row_has_the_box_width(self):
        top, left, rows = self.layout(cols=100)
        self.assertEqual(left, (100 - watch.POPUP_MAX_COLS) // 2 + 1)
        self.assertEqual({watch.display_width(r) for r in rows}, {watch.POPUP_MAX_COLS})

    def test_starts_on_the_second_row_leaving_the_first_free(self):
        self.assertEqual(self.layout(body_rows=20)[0], 2)

    def test_content_is_title_with_badge_detail_and_hint(self):
        _, _, rows = self.layout()
        text = "\n".join(plain(r) for r in rows)
        self.assertRegex(text, r"! +Panelle bağlantı koptu")
        self.assertIn("ConnectionClosedError: keepalive ping timeout", text)
        self.assertIn("Otomatik yeniden denenir · x: gizle", text)
        self.assertTrue(plain(rows[0]).startswith("┌") and plain(rows[-1]).startswith("└"))
        self.assertIn(watch.STYLE_BADGE, rows[1])

    def test_no_detail_means_no_detail_rows(self):
        _, _, rows = self.layout(detail="")
        self.assertEqual(len(rows), 4)   # üst, başlık, ipucu, alt

    def test_long_detail_is_cut_to_two_lines_with_an_ellipsis(self):
        _, _, rows = self.layout(detail="word " * 60)
        self.assertEqual(len(rows), 6)   # üst, başlık, 2 detay, ipucu, alt
        self.assertIn("…", plain(rows[3]))

    def test_narrow_terminal_shrinks_the_box_and_keeps_the_hide_key_visible(self):
        _, left, rows = self.layout(cols=watch.POPUP_MIN_COLS, hint="Panel kapalı ya da yeniden başlıyor olabilir")
        self.assertEqual(left, 1)
        self.assertEqual({watch.display_width(r) for r in rows}, {watch.POPUP_MIN_COLS})
        self.assertIn("x: gizle", plain(rows[-2]))

    def test_too_narrow_terminal_gets_no_box(self):
        self.assertIsNone(self.layout(cols=watch.POPUP_MIN_COLS - 1))

    def test_short_terminal_moves_up_then_gives_up(self):
        rows_needed = len(self.layout()[2])
        self.assertEqual(self.layout(body_rows=rows_needed + 2)[0], 2)
        self.assertEqual(self.layout(body_rows=rows_needed + 1)[0], 1)
        self.assertEqual(self.layout(body_rows=rows_needed)[0], 1)
        self.assertIsNone(self.layout(body_rows=rows_needed - 1))

    def test_a_very_long_title_is_cut_to_the_box(self):
        _, _, rows = self.layout(title="T" * 200)
        self.assertEqual({watch.display_width(r) for r in rows}, {watch.POPUP_MAX_COLS})

    def test_build_popup_positions_every_row_absolutely(self):
        layout = self.layout()
        out = watch.build_popup(layout)
        top, left, rows = layout
        for i, row in enumerate(rows):
            self.assertIn(f"{ESC}[{top + i};{left}H{row}", out)
        self.assertNotIn("\n", out)


class ViewerPopupTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.screen, self.out, self.dims = make_screen((80, 14))   # 13 gövde satırı + çubuk
        self.viewer = watch.Viewer("yuhem", "s1", self.screen, clock=self.clock)
        self.viewer.transport_name = "ws"

    def drawn(self):
        data = self.out.getvalue()
        self.out.truncate(0), self.out.seek(0)
        return data

    def go_down(self, detail="ConnectionRefusedError", **kw):
        self.viewer.apply_frame(good("v1\nv2\nv3"))
        self.viewer.render()
        self.drawn()
        self.viewer.apply_failure(detail, **kw)

    def test_a_short_outage_shows_the_status_bar_only(self):
        self.go_down()
        for _ in range(int(watch.POPUP_GRACE_SECONDS) - 1):
            self.clock.now += 1
            self.viewer.render()
        self.assertNotIn("┌", self.drawn())
        self.assertFalse(self.viewer.popup_visible())

    def test_the_popup_appears_once_the_grace_period_has_passed_on_top_of_the_repainted_body(self):
        self.go_down()
        self.clock.now += watch.POPUP_GRACE_SECONDS
        self.viewer.render()
        data = self.drawn()
        self.assertIn("┌", data)
        self.assertIn("Panele ulaşılamıyor", data)
        self.assertIn("ConnectionRefusedError", data)
        self.assertIn(watch.STYLE_RECONNECTING, data)
        self.assertLess(data.index("v1"), data.index("┌"))   # önce gövde, popup üstüne
        self.assertIn("yeniden bağlanıyor", data)            # çubuk de duruyor

    def test_a_steady_popup_is_not_redrawn_on_every_tick(self):
        self.go_down()
        self.clock.now += 5
        self.viewer.render()
        self.drawn()
        self.clock.now += 1
        self.viewer.set_retry_in(3.0)
        self.viewer.render()
        data = self.drawn()
        self.assertNotIn("┌", data)    # geri sayım yalnız çubukta
        self.assertNotIn("v1", data)
        self.assertIn("(3 sn)", data)

    def test_a_new_frame_while_the_popup_is_up_repaints_the_popup_on_top(self):
        self.go_down(detail="x unreachable: boom")
        self.clock.now += 5
        self.viewer.render()
        self.drawn()
        self.viewer.apply_frame({"ok": False, "error": "relay: henüz veri gelmedi"})   # hâlâ sorun, kare yok
        self.viewer.render()
        data = self.drawn()
        self.assertIn("┌", data)   # metin değişti: kutu yeniden
        self.assertIn("Uzak host bağlantısı koptu", data)

    def test_recovery_removes_the_popup_by_repainting_the_body(self):
        self.go_down()
        self.clock.now += 5
        self.viewer.render()
        self.drawn()
        self.viewer.apply_frame(good("v1\nv2\nv3"))   # aynı içerik, ama yine canlı
        self.viewer.render()
        data = self.drawn()
        self.assertNotIn("┌", data)
        self.assertIn(f"{ESC}[1;1Hv1", data)          # gövde yeniden çizildi (kutunun üstünü siler)
        self.assertIn("canlı", data)
        self.assertIsNone(self.viewer.trouble_since)

    def test_x_hides_the_popup_for_the_rest_of_the_outage_only(self):
        self.go_down()
        self.clock.now += 5
        self.viewer.render()
        self.drawn()
        self.viewer.dismiss_popup()
        self.viewer.render()
        data = self.drawn()
        self.assertNotIn("┌", data)
        self.assertIn(f"{ESC}[1;1Hv1", data)          # kutu kalktı: gövde yeniden
        self.viewer.apply_failure("ConnectionResetError: another")   # aynı sorun sürüyor
        self.clock.now += 5
        self.viewer.render()
        self.assertNotIn("┌", self.drawn())
        self.viewer.apply_frame(good("v1\nv2\nv3"))                  # düzeldi
        self.viewer.render()
        self.drawn()
        self.viewer.apply_failure("ConnectionRefusedError")          # yeni sorun: kutu geri gelir
        self.clock.now += 5
        self.viewer.render()
        self.assertIn("┌", self.drawn())

    def test_x_pressed_while_live_does_not_hide_the_popup_of_a_later_outage(self):
        self.viewer.apply_frame(good("v1\nv2\nv3"))
        self.viewer.dismiss_popup()
        self.viewer.apply_failure("ConnectionRefusedError")
        self.clock.now += 5
        self.viewer.render()
        self.assertIn("┌", self.drawn())

    def test_waiting_state_gets_a_blue_notice(self):
        self.viewer.apply_frame(good("v1\nv2\nv3"))
        self.viewer.apply_frame({"ok": False, "error": "s1: not running"})
        self.clock.now += watch.POPUP_GRACE_SECONDS
        self.viewer.render()
        data = self.drawn()
        self.assertIn("Session çalışmıyor", data)
        self.assertIn("s1: not running", data)
        self.assertIn(watch.STYLE_WAITING, data)

    def test_auth_failure_gets_the_red_popup(self):
        self.go_down("http 401: web.token bu panelle eşleşmiyor", severe=True)
        self.clock.now += 5
        self.viewer.render()
        data = self.drawn()
        self.assertIn("Yetki hatası", data)
        self.assertIn(watch.STYLE_SEVERE, data)

    def test_no_frame_ever_received_still_gets_a_popup_over_the_blank_body(self):
        self.viewer.apply_failure("ConnectionRefusedError")
        self.clock.now += 5
        self.viewer.render()
        self.assertIn("┌", self.drawn())

    def test_popup_is_skipped_when_the_terminal_is_too_small_but_the_bar_remains(self):
        self.dims["size"] = (80, 5)    # 4 gövde satırı: 5 satırlık kutu sığmaz
        self.go_down()
        self.clock.now += 5
        self.viewer.render()
        data = self.drawn()
        self.assertNotIn("┌", data)
        self.assertIn("yeniden bağlanıyor", data)

    def test_resizing_the_terminal_moves_the_popup(self):
        self.go_down()
        self.clock.now += 5
        self.viewer.render()
        first = self.drawn()
        self.assertIn(f"{ESC}[2;9H", first)     # 80 sütun: (80-64)//2+1
        self.dims["size"] = (120, 20)
        self.viewer.render()
        second = self.drawn()
        self.assertIn(f"{ESC}[2;29H", second)   # 120 sütun: (120-64)//2+1
        self.assertNotIn(f"{ESC}[2;9H", second)

    def test_connecting_state_never_shows_a_popup(self):
        self.clock.now += 60
        self.viewer.render()
        self.assertNotIn("┌", self.drawn())

    def test_the_popup_is_drawn_inside_the_body_never_over_the_status_bar(self):
        self.go_down()
        self.clock.now += 5
        self.viewer.render()
        data = self.drawn()
        rows = [int(m.group(1)) for m in re.finditer(r"\x1b\[(\d+);\d+H\x1b\[0;48;5;130;38;5;255m[┌│└]", data)]
        self.assertTrue(rows)
        self.assertLessEqual(max(rows), 13)   # ekran 14 satır: 14. satır çubuk


# ── taşıyıcılar ──────────────────────────────────────────────────────────────────────────

class FakePanel:
    """Gerçek bir HTTP sunucusu (127.0.0.1, rastgele port): istekleri kaydeder."""

    def __init__(self, token="tok", responder=None):
        self.token = token
        self.responder = responder or (lambda query: (200, good()))
        self.requests = []
        panel = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                auth = self.headers.get("Authorization")
                panel.requests.append({"path": parsed.path, "query": query, "auth": auth})
                if auth != f"Bearer {panel.token}":
                    status, obj = 401, {"ok": False, "error": "unauthorized"}
                else:
                    status, obj = panel.responder(query)
                body = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RestTransportTests(unittest.TestCase):
    def setUp(self):
        self.panel = FakePanel()
        self.addCleanup(self.panel.close)

    def transport(self, **kw):
        return watch.RestTransport(self.panel.port, "yuhem", "s 1", read_token=lambda: "tok", **kw)

    def test_request_shape_and_bearer_auth(self):
        frame = self.transport().fetch()
        self.assertEqual(frame, good())
        req = self.panel.requests[0]
        self.assertEqual(req["path"], "/api/term/output")
        self.assertEqual(req["query"], {"name": "s 1", "host": "yuhem", "lang": "en", "lite": "1", "viewport": "1"})
        self.assertEqual(req["auth"], "Bearer tok")
        self.assertNotIn("token", req["query"])   # token URL'ye girmez

    def test_ok_false_body_is_returned_not_raised(self):
        self.panel.responder = lambda q: (200, {"ok": False, "error": "yuhem unreachable: timed out"})
        self.assertEqual(self.transport().fetch()["error"], "yuhem unreachable: timed out")

    def test_wrong_token_is_an_auth_error(self):
        t = watch.RestTransport(self.panel.port, "yuhem", "s1", read_token=lambda: "wrong")
        with self.assertRaises(watch.TransportError) as cm:
            t.fetch()
        self.assertTrue(cm.exception.auth)
        self.assertIn("401", cm.exception.detail)

    def test_other_http_errors(self):
        self.panel.responder = lambda q: (500, {"ok": False})
        with self.assertRaises(watch.TransportError) as cm:
            self.transport().fetch()
        self.assertFalse(cm.exception.auth)
        self.assertIn("500", cm.exception.detail)

    def test_non_json_and_non_dict_bodies(self):
        for body in (b"<html>", b"[1,2]"):
            self.panel.responder = lambda q, b=body: (200, b)
            with self.assertRaises(watch.TransportError):
                self.transport().fetch()

    def test_connection_refused(self):
        port = self.panel.port
        self.panel.close()
        t = watch.RestTransport(port, "yuhem", "s1", read_token=lambda: "tok")
        with self.assertRaises(watch.TransportError):
            t.fetch()

    def test_token_is_re_read_on_every_fetch(self):
        tokens = iter(["wrong", "tok"])
        t = watch.RestTransport(self.panel.port, "yuhem", "s1", read_token=lambda: next(tokens))
        with self.assertRaises(watch.TransportError):
            t.fetch()
        self.assertEqual(t.fetch(), good())   # token dosyası tazelendi → bu sefer geçer

    def test_frames_polls_faster_when_live_than_when_waiting(self):
        clock = Clock()
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            clock.now += s

        self.panel.responder = lambda q: (200, good())
        t = self.transport(clock=clock, sleep=sleep)
        stop = threading.Event()
        gen = t.frames(stop, 0.25)
        seen = []
        for item in gen:
            seen.append(item)
            if len(seen) == 6:
                break
        gen.close()
        self.assertEqual(seen[0], good())
        self.assertEqual(seen[1:5], [None] * 4)    # 1 sn / 0,25 sn = 4 sessiz tick
        self.assertEqual(seen[5], good())          # sonra yeni yoklama
        self.assertEqual(len(self.panel.requests), 2)

        self.panel.requests.clear()
        self.panel.responder = lambda q: (200, {"ok": False, "error": "s1: not running"})
        clock.now = 0.0
        gen = t.frames(stop, 0.25)
        n = 0
        for item in gen:
            n += 1
            if len(self.panel.requests) == 2:
                break
        gen.close()
        self.assertEqual(n, 1 + 20 + 1)   # ilk yoklama + 5 sn / 0,25 sn = 20 sessiz tick + ikinci yoklama


class FakeWS:
    """`websockets.sync` ClientConnection yerine: recv(timeout) kuyruktan okur."""

    def __init__(self, items=()):
        self._q = queue.Queue()
        for it in items:
            self._q.put(it)
        self.closed = False

    def push(self, item):
        self._q.put(item)

    def recv(self, timeout=None):
        try:
            item = self._q.get(timeout=0.001 if timeout else None)
        except queue.Empty:
            raise TimeoutError("timed out")
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.closed = True


def term_msg(data):
    return json.dumps({"type": "term", "data": data})


class WsTransportTests(unittest.TestCase):
    def make(self, ws, clock=None, port=8765):
        self.calls = []

        def connect(url, **kwargs):
            self.calls.append((url, kwargs))
            if isinstance(ws, BaseException):
                raise ws
            return ws

        return watch.WsTransport(port, "yuhem", "s1", connect=connect, read_token=lambda: "tok",
                                 clock=clock or Clock())

    def test_connect_request_shape(self):
        ws = FakeWS([term_msg(good())])
        t = self.make(ws)
        gen = t.frames(threading.Event(), 0.25)
        next(gen)
        gen.close()
        url, kwargs = self.calls[0]
        parts = urllib.parse.urlsplit(url)
        self.assertEqual((parts.scheme, parts.netloc, parts.path), ("ws", "127.0.0.1:8765", "/ws/term"))
        self.assertEqual(dict(urllib.parse.parse_qsl(parts.query)),
                         {"name": "s1", "host": "yuhem", "lang": "en", "lite": "1", "viewport": "1", "interval": "1"})
        self.assertNotIn("tok", url)   # token URL'de değil
        self.assertEqual(kwargs["additional_headers"], {"Authorization": "Bearer tok"})
        self.assertGreaterEqual(kwargs["max_size"], 1024 * 1024)   # `lite`siz tam kare sığmalı
        self.assertLessEqual(kwargs["close_timeout"], 2.0)         # `q` ile çıkış 10 sn takılmasın
        self.assertIn("ping_interval", kwargs)
        self.assertIsNone(kwargs["ping_interval"])   # kütüphane keepalive'ı kapalı: canlılığı görüntüleyici izler
        self.assertTrue(ws.closed)

    def test_term_messages_are_unwrapped_and_other_messages_become_ticks(self):
        ws = FakeWS([term_msg(good("a")), json.dumps({"type": "status", "data": {}}), "not json", b"\x00",
                     term_msg({"ok": False, "error": "x"})])
        gen = self.make(ws).frames(threading.Event(), 0.25)
        got = [next(gen) for _ in range(5)]
        gen.close()
        self.assertEqual(got, [good("a"), None, None, None, {"ok": False, "error": "x"}])

    def test_quiet_connection_yields_ticks(self):
        gen = self.make(FakeWS()).frames(threading.Event(), 0.25)
        self.assertEqual([next(gen) for _ in range(3)], [None, None, None])
        gen.close()

    def test_silence_watchdog(self):
        clock = Clock()
        ws = FakeWS()
        t = self.make(ws, clock=clock)
        gen = t.frames(threading.Event(), 0.25)
        self.assertIsNone(next(gen))
        clock.now += watch.WS_SILENCE_SECONDS + 1
        with self.assertRaises(watch.TransportError) as cm:
            next(gen)
        self.assertIn("ses yok", cm.exception.detail)
        self.assertTrue(ws.closed)

    def test_a_frame_resets_the_silence_watchdog(self):
        clock = Clock()
        ws = FakeWS()
        gen = self.make(ws, clock=clock).frames(threading.Event(), 0.25)
        clock.now += watch.WS_SILENCE_SECONDS - 1
        ws.push(term_msg(good()))
        self.assertEqual(next(gen), good())
        clock.now += watch.WS_SILENCE_SECONDS - 1
        self.assertIsNone(next(gen))   # süre frame'den itibaren sayılır
        gen.close()

    def test_connection_closed_becomes_transport_error(self):
        ws = FakeWS([ConnectionResetError("peer reset")])
        gen = self.make(ws).frames(threading.Event(), 0.25)
        with self.assertRaises(watch.TransportError) as cm:
            next(gen)
        self.assertIn("ConnectionResetError", cm.exception.detail)
        self.assertFalse(cm.exception.auth)
        self.assertTrue(ws.closed)

    def test_connect_failure_becomes_transport_error(self):
        gen = self.make(ConnectionRefusedError(111, "Connection refused")).frames(threading.Event(), 0.25)
        with self.assertRaises(watch.TransportError):
            next(gen)

    def test_handshake_401_is_an_auth_error(self):
        class Rejected(Exception):
            response = type("R", (), {"status_code": 401})()

        gen = self.make(Rejected("server rejected WebSocket connection: HTTP 401")).frames(threading.Event(), 0.25)
        with self.assertRaises(watch.TransportError) as cm:
            next(gen)
        self.assertTrue(cm.exception.auth)

    def test_handshake_other_status(self):
        class Rejected(Exception):
            response = type("R", (), {"status_code": 502})()

        gen = self.make(Rejected("bad gateway")).frames(threading.Event(), 0.25)
        with self.assertRaises(watch.TransportError) as cm:
            next(gen)
        self.assertFalse(cm.exception.auth)
        self.assertIn("502", cm.exception.detail)

    def test_stop_ends_the_stream_cleanly_and_closes(self):
        ws = FakeWS()
        stop = threading.Event()
        gen = self.make(ws).frames(stop, 0.25)
        self.assertIsNone(next(gen))
        stop.set()
        self.assertEqual(list(gen), [])
        self.assertTrue(ws.closed)


@unittest.skipUnless(watch.import_ws_connect(), "websockets kurulu değil")
class RealWebsocketTests(unittest.TestCase):
    """Gerçek `websockets` istemcisi ↔ gerçek `websockets` sunucusu (127.0.0.1): başlıkla yetki,
    zarf çözme ve 16 MiB'a kadar mesaj."""

    def setUp(self):
        from websockets.sync.server import serve
        self.seen = []

        def handler(conn):
            self.seen.append({"path": conn.request.path, "auth": conn.request.headers.get("Authorization")})
            conn.send(term_msg(good("hello")))
            conn.send(term_msg(good("x" * 3_000_000)))   # `lite`siz eski panel gibi: >1 MiB
            for _ in conn:
                pass

        self.server = serve(handler, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)

    def test_end_to_end(self):
        t = watch.WsTransport(self.port, "yuhem", "s1", connect=watch.import_ws_connect(), read_token=lambda: "tok")
        gen = t.frames(threading.Event(), 0.25)
        first = next(gen)
        big = next(gen)
        gen.close()
        self.assertEqual(first["text"], "hello")
        self.assertEqual(len(big["text"]), 3_000_000)
        self.assertEqual(self.seen[0]["auth"], "Bearer tok")
        self.assertTrue(self.seen[0]["path"].startswith("/ws/term?"))


# ── denetleyici döngü ───────────────────────────────────────────────────────────────────────

STOP = object()   # betik öğesi: `stop`u set eder (gerçek taşıyıcılar yalnız böyle ya da istisnayla biter)


class Script:
    """Sahte taşıyıcı. Her `frames()` çağrısı sıradaki betiği oynatır; betik öğeleri: kare (dict),
    None (sessiz tick), istisna (fırlatılır), STOP (stop'u set eder), çağrılabilir (yan etki, kare
    üretmez). Betik istisnasız ve STOP'suz biterse akış "temiz kapandı" demektir. Betikler tükenince
    `stop` set edilir (döngü kendiliğinden bitmez, test bitirir)."""

    def __init__(self, name, scripts):
        self.name = name
        self._scripts = list(scripts)
        self.calls = 0

    def frames(self, stop, tick):
        self.calls += 1
        if not self._scripts:
            stop.set()
            return
        for item in self._scripts.pop(0):
            if isinstance(item, BaseException):
                raise item
            if item is STOP:
                stop.set()
                continue
            if callable(item):
                item()
                continue
            yield item


class RecordingBackoff(watch.Backoff):
    def __init__(self):
        super().__init__(rand=lambda: 1.0)   # deterministik: 1, 2, 4, 8, 15
        self.delays = []

    def next(self):
        delay = super().next()
        self.delays.append(delay)
        return delay


class WatchLoopTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.sleeps = []
        self.stop = threading.Event()
        self.screen, self.out, _ = make_screen((80, 6))
        self.viewer = watch.Viewer("yuhem", "s1", self.screen, clock=self.clock)
        self.backoff = RecordingBackoff()

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 3))
        self.clock.now += seconds

    def run_loop(self, ws, rest, mode="auto", keys=None):
        watch.watch_loop(self.viewer, ws, rest, mode=mode, stop=self.stop, keys=keys, backoff=self.backoff,
                         clock=self.clock, sleep=self.sleep)

    def test_ws_frames_reach_the_viewer(self):
        ws = Script("ws", [[good("hello"), None, good("hello world"), STOP]])
        self.run_loop(ws, Script("rest", []))
        self.assertEqual(self.viewer.frame["text"], "hello world")
        self.assertEqual(self.viewer.state, "live")
        self.assertEqual(self.viewer.transport_name, "ws")

    def test_ws_failure_falls_back_to_rest_immediately_without_sleeping(self):
        ws = Script("ws", [[watch.TransportError("refused")]])
        rest = Script("rest", [[good("from rest"), STOP]])
        self.run_loop(ws, rest)
        self.assertEqual(self.viewer.frame["text"], "from rest")
        self.assertEqual(self.sleeps, [])
        self.assertEqual((ws.calls, rest.calls), (1, 1))

    def test_rest_window_expires_and_ws_is_tried_again(self):
        advance = lambda: setattr(self.clock, "now", self.clock.now + watch.REST_FALLBACK_SECONDS + 1)
        ws = Script("ws", [[watch.TransportError("refused")], [good("ws is back"), STOP]])
        rest = Script("rest", [[good("from rest"), advance, None, None]])
        self.run_loop(ws, rest)
        self.assertEqual(self.viewer.frame["text"], "ws is back")
        self.assertEqual(self.viewer.transport_name, "ws")
        self.assertEqual(self.sleeps, [])

    def test_everything_down_backs_off_exponentially_and_never_exits_on_its_own(self):
        ws = Script("ws", [[watch.TransportError("refused")]])
        rest = Script("rest", [[watch.TransportError("refused")]] * 5)
        self.run_loop(ws, rest)
        self.assertEqual(self.backoff.delays, [1.0, 2.0, 4.0, 8.0, 15.0])   # tavan 15
        self.assertEqual(sum(self.sleeps), 30.0)                            # beklemeler gerçekten uygulandı
        self.assertLessEqual(max(self.sleeps), watch.TICK_SECONDS)          # parça parça (geri sayım + tuş dinleme)
        self.assertEqual(self.viewer.state, "reconnecting")

    def test_auth_failure_does_not_try_rest_and_is_marked_severe(self):
        ws = Script("ws", [[watch.TransportError("http 401", auth=True)]])
        rest = Script("rest", [])
        self.run_loop(ws, rest)
        self.assertEqual(rest.calls, 0)
        self.assertTrue(self.viewer.severe)
        self.assertIn("401", self.viewer.detail)
        self.assertGreater(sum(self.sleeps), 0)   # üstel beklemeye girdi

    def test_mode_ws_never_uses_rest(self):
        ws = Script("ws", [[watch.TransportError("refused")], [good("later"), STOP]])
        rest = Script("rest", [])
        self.run_loop(ws, rest, mode="ws")
        self.assertEqual(rest.calls, 0)
        self.assertEqual(self.viewer.frame["text"], "later")
        self.assertGreaterEqual(sum(self.sleeps), 1.0)

    def test_mode_rest_never_uses_ws(self):
        ws = Script("ws", [])
        rest = Script("rest", [[good("polled"), STOP]])
        self.run_loop(ws, rest, mode="rest")
        self.assertEqual(ws.calls, 0)
        self.assertEqual(self.viewer.frame["text"], "polled")

    def test_no_websockets_package_means_rest_only(self):
        rest = Script("rest", [[good("polled"), STOP]])
        self.run_loop(None, rest)
        self.assertEqual(self.viewer.frame["text"], "polled")

    def test_ws_that_drops_after_frames_reconnects_after_a_short_wait(self):
        ws = Script("ws", [[good("one"), watch.TransportError("dropped")], [good("two"), STOP]])
        self.run_loop(ws, Script("rest", []))
        self.assertEqual(self.viewer.frame["text"], "two")
        self.assertEqual(sum(self.sleeps), 1.0)   # kare geldiği için bekleme 1 sn'den başladı, REST'e düşmedi

    def test_clean_end_of_a_ws_stream_is_treated_as_a_dropped_connection(self):
        ws = Script("ws", [[good("one")], [good("two"), STOP]])   # ilk akış istisnasız biter
        self.run_loop(ws, Script("rest", []))
        self.assertEqual(self.viewer.frame["text"], "two")
        self.assertEqual(sum(self.sleeps), 1.0)

    def test_session_gone_frames_keep_the_connection_and_the_last_screen(self):
        ws = Script("ws", [[good("alive"), {"ok": False, "error": "s1: not running"}, None, STOP]])
        self.run_loop(ws, Script("rest", []))
        self.assertEqual(self.viewer.state, "waiting")
        self.assertEqual(self.viewer.frame["text"], "alive")
        self.assertEqual(self.sleeps, [])    # yeniden bağlanma yok

    def test_unexpected_exception_does_not_kill_the_viewer(self):
        ws = Script("ws", [[RuntimeError("bug")], [good("still here"), STOP]])
        with mock.patch.object(watch, "diag_log") as log:
            self.run_loop(ws, Script("rest", []), mode="ws")
        self.assertEqual(self.viewer.frame["text"], "still here")
        self.assertEqual(log.call_args[0][0], "watch_internal_error")

    def test_q_quits(self):
        class Keys:
            def __init__(self):
                self.polls = 0

            def poll(self):
                self.polls += 1
                return "q" if self.polls >= 3 else ""

        ws = Script("ws", [[good("a"), None, None, None, None, None]])
        self.run_loop(ws, Script("rest", []), keys=Keys())
        self.assertTrue(self.stop.is_set())

    def test_q_quits_during_the_reconnect_wait(self):
        class Keys:
            def poll(self):
                return "Q"

        ws = Script("ws", [[watch.TransportError("x", auth=True)]])
        self.run_loop(ws, Script("rest", []), keys=Keys())
        self.assertTrue(self.stop.is_set())
        self.assertEqual(self.sleeps, [])

    def test_x_during_the_reconnect_wait_hides_the_popup(self):
        class Keys:
            def __init__(self):
                self.polls = 0

            def poll(self):
                self.polls += 1
                return "x" if self.polls == 12 else ""   # ~3 sn bekleme, sonra kutu açıkken bas

        ws = Script("ws", [[watch.TransportError("ConnectionRefusedError")]] * 3)
        self.run_loop(ws, Script("rest", []), mode="ws", keys=Keys())
        self.assertTrue(self.viewer.popup_hidden)
        self.assertFalse(self.stop.is_set() and self.sleeps == [])   # çıkmadı, bekleme gerçekten işledi

    def test_popup_shows_up_during_a_long_outage_in_the_loop(self):
        ws = Script("ws", [[good("last"), watch.TransportError("ConnectionRefusedError")]]
                    + [[watch.TransportError("ConnectionRefusedError")]] * 3)
        self.run_loop(ws, Script("rest", []), mode="ws")
        self.assertIn("┌", self.out.getvalue())
        self.assertIn("Panele ulaşılamıyor", self.out.getvalue())

    def test_dead_screen_ends_the_loop(self):
        self.screen.dead = True
        ws = Script("ws", [[good("a")]])
        self.run_loop(ws, Script("rest", []))
        self.assertEqual(ws.calls, 0)


class WantsQuitTests(unittest.TestCase):
    def test_plain_q(self):
        for chunk in ("q", "Q", "xq", "q\n", "aQb"):
            self.assertTrue(watch.wants_quit(chunk), chunk)

    def test_other_keys_do_not_quit(self):
        for chunk in ("", "a", "\r", " ", "hello"):
            self.assertFalse(watch.wants_quit(chunk), chunk)

    def test_q_inside_an_escape_sequence_does_not_quit(self):
        for chunk in ("\x1bOQ",          # F2
                      "\x1b[1;2Q",       # değiştirilmiş F2
                      "\x1b[A", "\x1b[1;5C", "\x1bOP", "\x1bq"):   # oklar, F1, Alt+q
            self.assertFalse(watch.wants_quit(chunk), repr(chunk))

    def test_q_next_to_an_escape_sequence_still_quits(self):
        self.assertTrue(watch.wants_quit("\x1b[Aq"))


class WantsDismissTests(unittest.TestCase):
    def test_plain_x(self):
        for chunk in ("x", "X", "ax", "x\n"):
            self.assertTrue(watch.wants_dismiss(chunk), chunk)

    def test_other_keys_do_not_dismiss(self):
        for chunk in ("", "a", "q", "\r", "hello"):
            self.assertFalse(watch.wants_dismiss(chunk), chunk)

    def test_x_inside_an_escape_sequence_does_not_dismiss(self):
        for chunk in ("\x1b[1;5x", "\x1bOx", "\x1bx"):
            self.assertFalse(watch.wants_dismiss(chunk), repr(chunk))


class QuitRequestedTests(unittest.TestCase):
    class Keys:
        def __init__(self, *chunks):
            self.chunks = list(chunks)

        def poll(self):
            return self.chunks.pop(0) if self.chunks else ""

    def setUp(self):
        self.stop = threading.Event()
        self.screen, _, _ = make_screen()
        self.viewer = watch.Viewer("yuhem", "s1", self.screen)

    def test_x_hides_the_popup_without_quitting(self):
        self.viewer.apply_failure("ConnectionRefusedError")
        self.assertFalse(watch._quit_requested(self.Keys("x"), self.stop, self.viewer))
        self.assertTrue(self.viewer.popup_hidden)
        self.assertFalse(self.stop.is_set())

    def test_x_while_everything_is_fine_does_not_suppress_the_next_outage(self):
        self.viewer.apply_frame(good())
        watch._quit_requested(self.Keys("x"), self.stop, self.viewer)
        self.assertFalse(self.viewer.popup_hidden)

    def test_q_quits_and_does_not_hide(self):
        self.assertTrue(watch._quit_requested(self.Keys("q"), self.stop, self.viewer))
        self.assertFalse(self.viewer.popup_hidden)

    def test_x_without_a_viewer_is_ignored(self):
        self.assertFalse(watch._quit_requested(self.Keys("x"), self.stop))

    def test_no_keys_object(self):
        self.assertFalse(watch._quit_requested(None, self.stop, self.viewer))
        self.stop.set()
        self.assertTrue(watch._quit_requested(None, self.stop, self.viewer))


# ── --once ────────────────────────────────────────────────────────────────────────────────

class RunOnceTests(unittest.TestCase):
    def setUp(self):
        self.panel = FakePanel()
        self.addCleanup(self.panel.close)
        p = mock.patch.object(watch, "read_token", lambda: "tok")
        p.start()
        self.addCleanup(p.stop)

    def run_once(self, plain=False):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = watch.run_once("yuhem", "s1", self.panel.port, plain)
        return code, out.getvalue(), err.getvalue()

    def test_prints_the_frame(self):
        # tam kare (lite:false): sondaki "\n" capture-pane'in terminatörü, çıktıya iki kez girmez
        self.panel.responder = lambda q: (200, good(f"{ESC}[31mred{ESC}[0m\nplain\n", lite=False))
        code, out, _ = self.run_once()
        self.assertEqual(code, 0)
        self.assertEqual(out, f"{ESC}[31mred{ESC}[0m\nplain\n")
        self.assertEqual(self.panel.requests[0]["query"]["lite"], "1")

    def test_a_lite_frame_with_blank_last_rows_prints_all_its_rows(self):
        self.panel.responder = lambda q: (200, good("a\nb\n\n", rows=4))   # a, b, boş, boş
        _, out, _ = self.run_once()
        self.assertEqual(out.count("\n"), 4)   # tam 4 satır

    def test_plain_strips_colors(self):
        self.panel.responder = lambda q: (200, good(f"{ESC}[31mred{ESC}[0m"))
        self.assertEqual(self.run_once(plain=True)[1], "red\n")

    def test_session_not_running_is_exit_1_with_the_reason(self):
        self.panel.responder = lambda q: (200, {"ok": False, "error": "s1: not running"})
        code, out, err = self.run_once()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("yuhem:s1: s1: not running", err)

    def test_panel_down_is_exit_1(self):
        self.panel.close()
        code, out, err = self.run_once()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("cops watch:", err)


# ── terminale sızıntı ───────────────────────────────────────────────────────────────────────

def _root_has_handlers():
    return bool(logging.getLogger().handlers)


class QuietTerminalTests(unittest.TestCase):
    def test_library_logging_goes_to_diag_log_not_to_stderr(self):
        err = io.StringIO()
        with mock.patch.object(watch, "diag_log") as log, contextlib.redirect_stderr(err):
            with watch.quiet_terminal("yuhem:s1"):
                try:
                    raise ValueError("boom")
                except ValueError:
                    logging.getLogger("websockets.client").error("keepalive ping failed", exc_info=True)
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(log.call_args[0][0], "watch_lib_log")
        fields = log.call_args[1]
        self.assertEqual((fields["target"], fields["msg"], fields["logger"]),
                         ("yuhem:s1", "keepalive ping failed", "websockets.client"))
        self.assertIn("ValueError: boom", fields["error"])

    @unittest.skipIf(_root_has_handlers(), "başka bir test kök logger'a handler koymuş")
    def test_control_the_same_call_without_it_does_leak_to_stderr(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            logging.getLogger("websockets.client").error("keepalive ping failed")
        self.assertIn("keepalive ping failed", err.getvalue())

    def test_handler_is_removed_on_exit(self):
        before = list(logging.getLogger().handlers)
        with watch.quiet_terminal("t"):
            self.assertEqual(len(logging.getLogger().handlers), len(before) + 1)
        self.assertEqual(logging.getLogger().handlers, before)

    def test_thread_exceptions_are_logged_not_printed_and_the_hook_is_restored(self):
        err = io.StringIO()
        original = threading.excepthook
        with mock.patch.object(watch, "diag_log") as log, contextlib.redirect_stderr(err):
            with watch.quiet_terminal("t"):
                th = threading.Thread(target=lambda: 1 / 0, name="bad-thread")
                th.start()
                th.join()
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(log.call_args[0][0], "watch_thread_error")
        self.assertEqual(log.call_args[1]["thread"], "bad-thread")
        self.assertIn("ZeroDivisionError", log.call_args[1]["error"])
        self.assertIs(threading.excepthook, original)

    def test_system_exit_in_a_thread_is_not_logged(self):
        with mock.patch.object(watch, "diag_log") as log:
            with watch.quiet_terminal("t"):
                th = threading.Thread(target=lambda: sys.exit(0))
                th.start()
                th.join()
        log.assert_not_called()

    def test_handler_throttles_a_flapping_connection(self):
        clock = Clock()
        with mock.patch.object(watch, "diag_log") as log:
            h = watch._DiagLogHandler("t", clock=clock)
            rec = logging.LogRecord("websockets.client", logging.ERROR, __file__, 1, "x", None, None)
            h.emit(rec)
            clock.now += watch._DiagLogHandler.MIN_INTERVAL_SECONDS - 1
            h.emit(rec)
            self.assertEqual(log.call_count, 1)
            clock.now += 2
            h.emit(rec)
            self.assertEqual(log.call_count, 2)

    def test_handler_ignores_records_below_warning(self):
        with mock.patch.object(watch, "diag_log") as log, watch.quiet_terminal("t"):
            logging.getLogger("websockets.client").info("connection open")
        log.assert_not_called()


@unittest.skipUnless(watch.import_ws_connect(), "websockets kurulu değil")
class KeepaliveFailureTests(unittest.TestCase):
    """Kullanıcının mirror penceresinde gördüğü hatanın birebir tekrarı: sunucu Ping'e Pong vermiyor (web_ws'in
    eski hatası), istemci kütüphanesinin keepalive'ı bağlantıyı "1011 keepalive ping timeout" ile keser ve
    traceback'i `logging` ile terminale basar."""

    def setUp(self):
        from websockets.server import ServerProtocol
        self.done = threading.Event()
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.addCleanup(self.listener.close)
        self.addCleanup(self.done.set)

        def serve():
            conn, _ = self.listener.accept()
            protocol = ServerProtocol()
            protocol.receive_data(conn.recv(65536))
            protocol.send_response(protocol.accept(protocol.events_received()[0]))
            conn.sendall(b"".join(protocol.data_to_send()))
            conn.settimeout(0.1)
            while not self.done.is_set():   # okur ama HİÇBİR ŞEYE yanıt vermez: Pong yok, close-ack yok
                try:
                    if not conn.recv(65536):
                        break
                except socket.timeout:
                    pass
                except OSError:
                    break
            conn.close()

        threading.Thread(target=serve, daemon=True).start()

    def run_client(self):
        connect = watch.import_ws_connect()
        conn = connect(f"ws://127.0.0.1:{self.port}/", ping_interval=0.1, ping_timeout=0.2, close_timeout=0.2)
        try:
            with self.assertRaises(Exception) as cm:
                conn.recv(timeout=10)
            time.sleep(0.6)   # keepalive thread'inin hata günlüğünü basmasına izin ver
            return cm.exception
        finally:
            conn.close()

    def test_the_failure_is_the_one_from_the_bug_report(self):
        with contextlib.redirect_stderr(io.StringIO()):   # kütüphane traceback'i basacak: test çıktısını kirletmesin
            exc = self.run_client()
        self.assertIn("keepalive ping timeout", str(exc))
        self.assertIn("ConnectionClosedError", watch._ws_error(exc).detail)

    @unittest.skipIf(_root_has_handlers(), "başka bir test kök logger'a handler koymuş")
    def test_control_without_quiet_terminal_the_traceback_leaks_to_stderr(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.run_client()
        self.assertIn("Traceback", err.getvalue())

    def test_with_quiet_terminal_nothing_reaches_stderr(self):
        err = io.StringIO()
        with mock.patch.object(watch, "diag_log") as log, contextlib.redirect_stderr(err):
            with watch.quiet_terminal("yuhem:s1"):
                self.run_client()
        self.assertEqual(err.getvalue(), "")
        self.assertIn("watch_lib_log", [c[0][0] for c in log.call_args_list])


class RegisterTests(unittest.TestCase):
    def test_subcommand_is_wired_into_the_cli(self):
        from claudeops import cli
        args = cli.build_parser().parse_args(["watch", "ulak_31:rustrino", "--port", "9000", "--once", "--plain"])
        self.assertIs(args.func, watch.run)
        self.assertEqual((args.target, args.port, args.once, args.plain, args.transport),
                         ("ulak_31:rustrino", 9000, True, True, "auto"))

    def test_run_rejects_a_bad_target(self):
        from claudeops import cli
        args = cli.build_parser().parse_args(["watch", "a b"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(watch.run(args), 2)

    def test_run_refuses_a_non_tty_stdout(self):
        from claudeops import cli
        args = cli.build_parser().parse_args(["watch", "x"])
        err = io.StringIO()
        with mock.patch.object(sys, "stdout", io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(watch.run(args), 2)
        self.assertIn("--once", err.getvalue())


if __name__ == "__main__":
    unittest.main()

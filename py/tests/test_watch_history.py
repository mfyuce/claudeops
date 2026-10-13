"""`py/cops watch` geçmişte kaydırma testleri (TBD#79): geçmiş kipi, sayfalı `GET /api/term/history` istemcisi,
gövde override'ı. Sahte geçmiş/saat/ekranla koşar (hiçbiri gerçekten beklemez); `HistoryClient` 127.0.0.1'de gerçek
bir stdlib HTTP sunucusuna, en sonda tüm görüntüleyici (alt süreç, kontrol terminali olan bir pty'de) sahte panele karşı.

Çalıştırma:  python3 -m unittest discover -s py/tests -p 'test_watch_history.py' -v
"""
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
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import watch  # noqa: E402

try:
    import pty
    import termios
except ImportError:  # pragma: no cover - Windows
    pty = termios = None

ESC = "\x1b"
UP, DOWN, PGUP, PGDN, HOME, END = f"{ESC}[A", f"{ESC}[B", f"{ESC}[5~", f"{ESC}[6~", f"{ESC}[H", f"{ESC}[F"
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


class FakeSender:
    def __init__(self):
        self.sent = []

    def submit(self, kind, payload):
        self.sent.append((kind, payload))
        return len(self.sent)

    def take_results(self):
        return []

    def close(self, wait=2.0):
        pass


class FakeHistory:
    """`HistoryClient` yerine. Satırın içeriği "mutlak kimliği" taşır (`A{no + history_size}`): geçmiş büyüyünce aynı
    içerik yeni numarayla gelir, hizalama testleri bunu kullanır."""

    def __init__(self, rows, hist, auto=True):
        self.rows, self.hist, self.auto = rows, hist, auto
        self.requests = []
        self._results = []
        self.closed = False

    def payload(self, start, end, hist=None):
        hist = self.hist if hist is None else hist
        s, e = max(start, -hist), min(end, self.rows - 1)
        return {"ok": True, "text": "\n".join(f"A{n + hist}" for n in range(s, e + 1)), "start": s, "end": e,
                "history_size": hist, "rows": self.rows, "cols": 80, "alternate_screen": False}

    def request(self, start, end):
        self.requests.append((start, end))
        if self.auto:
            self._results.append((start, end, self.payload(start, end), ""))

    def busy(self):
        return False

    def take_results(self):
        out, self._results = self._results, []
        return out

    def close(self):
        self.closed = True


class HistRig:
    """Gerçek `Viewer` + `InputController`; pane `rows` satır, `hist` satır geçmiş; pencere `size` (gövde = satır-1)."""

    def __init__(self, rows=10, hist=100, size=(80, 6), history=True, live=True, **frame_extra):
        self.clock = Clock()
        self.out = io.StringIO()
        self.dims = {"size": size}
        self.screen = watch.Screen(self.out, title="yuhem:s1", size_fn=lambda: self.dims["size"])
        self.viewer = watch.Viewer("yuhem", "s1", self.screen, clock=self.clock)
        self.sender = FakeSender()
        self.history = FakeHistory(rows, hist) if history else None
        self.ctl = watch.InputController(self.viewer, self.sender, history=self.history, clock=self.clock)
        self.viewer.overlay = self.ctl.bar
        self.rows, self.hist = rows, hist
        if live:
            self.live(**frame_extra)

    def live(self, **extra):
        kw = {"rows": self.rows, "history_size": self.hist}
        kw.update(extra)
        self.viewer.apply_frame(good(**kw))

    def press(self, *chunks):
        result = False
        for chunk in chunks:
            result = self.ctl.handle(chunk)
        return result

    def settle(self, times=3):
        for _ in range(times):
            self.ctl.handle("")

    def bar_text(self, cols=200):
        bar = self.ctl.bar(cols)
        return bar[0] if bar else None

    @property
    def shown(self):
        return self.viewer._body_override

    def content(self, top, view=5, hist=None):
        hist = self.hist if hist is None else hist
        return [f"A{n + hist}" for n in range(top, top + view)]


# ── geçmiş kipi ────────────────────────────────────────────────────────────────────────────

class EnterAndScrollTests(unittest.TestCase):
    """rows=10, geçmiş 100, pencere 6 satır (gövde 5): canlı konum top=5, görünen sayfa 5 satır."""

    def test_up_arrow_opens_history_one_line_above_the_live_view(self):
        rig = HistRig()
        rig.press(UP)
        self.assertEqual(rig.ctl.mode, "history")
        self.assertEqual(rig.ctl._h_top, 4)
        rig.settle()
        self.assertEqual(rig.shown, rig.content(4))

    def test_the_first_page_request_covers_a_screen_above_and_below(self):
        rig = HistRig()
        rig.press(UP)
        self.assertEqual(rig.history.requests, [(-1, 9)])   # (top - V, top + 2V - 1) pane sonuna kırpılı

    def test_nothing_is_drawn_from_history_until_the_page_has_arrived(self):
        rig = HistRig()
        rig.press(UP)
        self.assertIsNone(rig.shown)                         # sayfa yok: canlı görünüm yerinde kalır, yanıp sönme yok
        self.assertIn("yükleniyor", rig.bar_text())

    def test_the_other_opening_keys(self):
        for key, top in ((PGUP, 1), (f"{ESC}OA", 4), (HOME, -100), (f"{ESC}[1~", -100)):
            rig = HistRig()
            rig.press(key)
            self.assertEqual((key, rig.ctl.mode, rig.ctl._h_top), (key, "history", top))

    def test_down_and_end_keys_do_nothing_on_the_live_screen(self):
        rig = HistRig()
        rig.press(DOWN, PGDN, END)
        self.assertEqual(rig.ctl.mode, "normal")
        self.assertEqual(rig.history.requests, [])

    def test_arrows_move_one_line_and_pages_move_a_screen_minus_one(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        rig.press(UP, UP)
        self.assertEqual(rig.ctl._h_top, 2)
        rig.press(PGUP)
        self.assertEqual(rig.ctl._h_top, -2)          # 5 satırlık sayfa: 4 satır
        rig.press(DOWN)
        self.assertEqual(rig.ctl._h_top, -1)
        rig.press(PGDN)
        self.assertEqual(rig.ctl._h_top, 3)

    def test_the_wheel_arrives_as_repeated_arrows_in_one_read(self):
        rig = HistRig()
        rig.press(UP * 3)
        self.assertEqual(rig.ctl._h_top, 2)

    def test_home_goes_to_the_oldest_line_and_stops_there(self):
        rig = HistRig()
        rig.press(UP)
        rig.press(HOME)
        self.assertEqual(rig.ctl._h_top, -100)
        rig.press(UP, PGUP)
        self.assertEqual(rig.ctl._h_top, -100)
        rig.settle()
        self.assertEqual(rig.shown, rig.content(-100))

    def test_scrolling_down_to_the_live_position_returns_to_live(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        self.assertIsNotNone(rig.shown)
        rig.press(DOWN)
        self.assertEqual(rig.ctl.mode, "normal")
        self.assertIsNone(rig.shown)

    def test_a_page_down_past_the_live_position_also_returns(self):
        rig = HistRig()
        rig.press(UP, PGDN)
        self.assertEqual(rig.ctl.mode, "normal")

    def test_leaving_keys(self):
        for key in (END, f"{ESC}OF", f"{ESC}[4~", "G", ESC, "q", "Q"):
            rig = HistRig()
            rig.press(UP)
            rig.settle()
            self.assertFalse(rig.press(key), key)
            self.assertEqual(rig.ctl.mode, "normal", key)
            self.assertIsNone(rig.shown, key)

    def test_q_in_history_returns_to_live_instead_of_quitting(self):
        rig = HistRig()
        rig.press(UP)
        self.assertFalse(rig.press("q"))
        self.assertTrue(rig.press("q"))   # canlıdayken q çıkar

    def test_g_goes_to_the_oldest_line(self):
        rig = HistRig()
        rig.press(UP, "g")
        self.assertEqual(rig.ctl._h_top, -100)

    def test_other_keys_in_history_are_ignored(self):
        rig = HistRig()
        rig.press(UP)
        rig.press("a", "5", "\n", f"{ESC}[C", f"{ESC}[D", "\x04")
        self.assertEqual(rig.ctl.mode, "history")
        self.assertEqual(rig.ctl._h_top, 4)

    def test_pasted_text_never_acts_in_history(self):
        rig = HistRig()
        rig.press(UP)
        rig.press(f"{ESC}[200~q{ESC}[201~")
        self.assertEqual(rig.ctl.mode, "history")

    def test_the_input_modes_open_from_history_on_the_live_screen(self):
        for key, mode in (("i", "compose"), ("k", "keys"), ("R", "rawask")):
            rig = HistRig()
            rig.press(UP)
            rig.settle()
            rig.press(key)
            self.assertEqual(rig.ctl.mode, mode, key)
            self.assertIsNone(rig.shown, key)

    def test_x_leaves_history_and_hides_the_popup(self):
        rig = HistRig()
        rig.press(UP)
        rig.viewer.apply_failure("ConnectionRefusedError")
        rig.press("x")
        self.assertEqual(rig.ctl.mode, "normal")
        self.assertTrue(rig.viewer.popup_hidden)

    def test_arrows_still_mean_what_they_did_in_the_other_modes(self):
        rig = HistRig()
        rig.press("k", UP)                      # kısa tuş: oturuma Up gider, geçmiş açılmaz
        self.assertEqual(rig.sender.sent, [("key", "Up")])
        self.assertEqual(rig.ctl.mode, "normal")
        rig = HistRig()
        rig.press("iab", UP)                    # yazı satırı: ok yok sayılır
        self.assertEqual((rig.ctl.mode, rig.ctl.buf), ("compose", "ab"))
        rig = HistRig()
        rig.press("R", "\n", UP)                # ham geçiş: ok oturuma gider
        self.assertEqual(rig.sender.sent, [("raw", UP)])


class PagingTests(unittest.TestCase):
    def test_scrolling_inside_the_cache_makes_no_new_request(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        self.assertEqual(rig.history.requests, [(-1, 9)])
        rig.press(UP, UP)
        rig.settle()
        self.assertEqual(rig.history.requests, [(-1, 9)])
        self.assertEqual(rig.shown, rig.content(2))

    def test_scrolling_towards_the_edge_of_the_cache_prefetches_the_next_page(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        rig.press(PGUP)                    # top 0: önbellekte -1..9, yakın aralık -2..6 içinde -2 eksik
        self.assertEqual(rig.ctl._h_top, 0)
        self.assertEqual(rig.history.requests[-1], (-5, 9))
        rig.settle()
        self.assertEqual(rig.shown, rig.content(0))

    def test_a_far_jump_asks_for_the_page_around_the_target(self):
        rig = HistRig()
        rig.press(UP, HOME)
        rig.settle()
        self.assertEqual(rig.history.requests[-1], (-100, -91))
        self.assertEqual(rig.shown, rig.content(-100))

    def test_the_same_page_is_not_asked_for_twice_while_it_is_on_its_way(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        rig.settle(5)
        self.assertEqual(len(rig.history.requests), 1)

    def test_one_request_never_asks_for_more_than_the_servers_cap(self):
        rig = HistRig(rows=400, hist=1000, size=(80, 301))   # gövde 300 satır
        with mock.patch.object(watch, "HISTORY_MAX_REQUEST_LINES", 50):
            rig.press(UP)
        start, end = rig.history.requests[0]
        self.assertEqual(end - start + 1, 50)

    def test_the_default_cap_matches_the_servers(self):
        from claudeops.commands import web
        self.assertEqual(watch.HISTORY_MAX_REQUEST_LINES, web.TERM_HISTORY_MAX_LINES)

    def test_a_short_answer_is_padded_so_it_is_not_asked_for_again(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        payload = rig.history.payload(-1, 9)
        payload["text"] = "\n".join(payload["text"].split("\n")[:3])   # 11 satır istendi, 3 geldi
        rig.history._results.append((-1, 9, payload, ""))
        rig.settle()
        self.assertEqual(rig.ctl._h_lines[8], "")                      # eksikler boş sayılır
        self.assertEqual(len(rig.history.requests), 1)

    def test_an_answer_numbered_against_an_older_history_is_realigned(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        old = rig.history.payload(-5, -1, hist=98)           # istek yola çıktıktan sonra geçmiş 2 satır büyümüş
        rig.history._results.append((-5, -1, old, ""))
        rig.ctl.handle("")
        # yanıttaki -5 ... -1 bugünkü numaralamada -7 ... -3
        self.assertEqual([rig.ctl._h_lines[k] for k in range(-7, -2)], [f"A{n + 98}" for n in range(-5, 0)])

    def test_an_answer_from_a_newer_history_pulls_the_numbering_forward(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        new = rig.history.payload(-5, -1, hist=104)          # canlı kare henüz yetişmeden yanıt geldi
        rig.history._results.append((-5, -1, new, ""))
        rig.ctl.handle("")
        self.assertEqual(rig.ctl._h_ref, 104)
        self.assertEqual(rig.ctl._h_top, 4 - 4)
        self.assertEqual([rig.ctl._h_lines[k] for k in range(-5, 0)], [f"A{n + 104}" for n in range(-5, 0)])


class RealignTests(unittest.TestCase):
    def test_new_output_keeps_the_same_content_on_screen(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        before = list(rig.shown)
        rig.history.hist = 105
        rig.live(history_size=105)               # 5 satır büyüdü
        rig.settle()
        self.assertEqual(rig.ctl._h_ref, 105)
        self.assertEqual(rig.ctl._h_top, -1)     # içerik 5 satır yukarı kaydı
        self.assertEqual(rig.shown, before)

    def test_realigned_cache_needs_no_refetch_for_the_visible_lines(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        rig.history._results.append((-1, 9, rig.history.payload(-1, 9), ""))
        rig.settle()
        rig.history.requests.clear()
        rig.live(history_size=102)
        rig.ctl.handle("")
        self.assertEqual(rig.shown, rig.content(4, hist=100))           # yanıt gelmeden, önbellekten: içerik DEĞİŞMEDİ
        self.assertEqual(rig.ctl._h_top, 2)                             # yalnız numarası 2 kaydı
        # yeni çıktının satırları (alt kenar) önbellekte yok: yalnız o kenar için ön yükleme istenir, görünen sayfa için değil
        self.assertTrue(all(k in rig.ctl._h_lines for k in range(2, 7)))

    def test_history_that_stays_smaller_returns_to_live_with_a_notice(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        rig.live(history_size=50)                 # örneğin clear-history
        rig.settle()
        self.assertEqual(rig.ctl.mode, "history")  # kısa süreli düşüş bayat kare olabilir: hemen çıkılmaz
        rig.clock.now += watch.HISTORY_SHRINK_GRACE_SECONDS + 0.1
        rig.ctl.handle("")
        self.assertEqual(rig.ctl.mode, "normal")
        self.assertIsNone(rig.shown)
        self.assertIn("geçmiş değişti", rig.bar_text())

    def test_a_stale_live_frame_after_a_newer_page_answer_is_not_a_shrink(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        rig.history._results.append((-5, -1, rig.history.payload(-5, -1, hist=104), ""))
        rig.ctl.handle("")                         # yanıt canlı kareden yeni: numaralama 104'e çekildi
        self.assertEqual(rig.ctl._h_ref, 104)
        rig.live(history_size=100)                 # henüz yetişmemiş canlı kare
        rig.settle()
        self.assertEqual(rig.ctl.mode, "history")
        rig.live(history_size=104)                 # yetişti
        rig.clock.now += 10
        rig.settle()
        self.assertEqual(rig.ctl.mode, "history")

    def test_a_dip_that_recovers_never_counts(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        rig.live(history_size=90)
        rig.clock.now += watch.HISTORY_SHRINK_GRACE_SECONDS - 1
        rig.ctl.handle("")
        rig.live(history_size=100)
        rig.ctl.handle("")
        rig.live(history_size=90)
        rig.clock.now += watch.HISTORY_SHRINK_GRACE_SECONDS - 1     # toplam süre eşiği aşar ama araya iyileşme girdi
        rig.ctl.handle("")
        self.assertEqual(rig.ctl.mode, "history")

    def test_oldest_line_follows_the_growing_history(self):
        rig = HistRig()
        rig.press(UP, HOME)
        rig.settle()
        rig.history.hist = 104
        rig.live(history_size=104)
        rig.settle()
        rig.press(HOME)
        self.assertEqual(rig.ctl._h_top, -104)


class EntryConditionTests(unittest.TestCase):
    def test_no_connection_means_no_history_and_says_why(self):
        rig = HistRig()
        rig.viewer.apply_failure("ConnectionRefusedError")
        rig.press(UP)
        self.assertEqual(rig.ctl.mode, "normal")
        self.assertIn("geçmiş alınamaz", rig.bar_text())
        self.assertEqual(rig.history.requests, [])

    def test_no_frame_yet(self):
        rig = HistRig(live=False)
        rig.press(UP)
        self.assertEqual(rig.ctl.mode, "normal")

    def test_a_pane_with_no_history_that_fits_the_window_has_nothing_to_scroll(self):
        rig = HistRig(rows=4, hist=0)             # gövde 5 satır ≥ pane 4 satır
        rig.press(UP)
        self.assertEqual(rig.ctl.mode, "normal")
        self.assertEqual(rig.bar_text(), " kaydırılacak geçmiş yok")

    def test_a_window_shorter_than_the_pane_can_still_scroll_over_the_pane_itself(self):
        rig = HistRig(rows=10, hist=0)
        rig.press(UP)
        rig.settle()
        self.assertEqual(rig.ctl._h_top, 4)
        rig.press(HOME)
        self.assertEqual(rig.ctl._h_top, 0)

    def test_malformed_frames_are_not_scrollable(self):
        for extra in ({"rows": None}, {"history_size": None}, {"rows": 0}, {"history_size": "x"}):
            rig = HistRig(live=False)
            rig.viewer.apply_frame(good(**{"rows": 10, "history_size": 100, **extra}))
            rig.press(UP)
            self.assertEqual(rig.ctl.mode, "normal", extra)

    def test_without_a_history_client_the_keys_do_nothing(self):
        rig = HistRig(history=False)
        rig.press(UP, PGUP, HOME)
        self.assertEqual(rig.ctl.mode, "normal")

    def test_the_window_is_resized_while_looking_at_history(self):
        rig = HistRig(size=(80, 6))
        rig.press(UP, PGUP)                        # top 0
        rig.settle()
        self.assertEqual(len(rig.shown), 5)
        rig.dims["size"] = (80, 9)                 # gövde 8 satır
        rig.settle()
        self.assertEqual(rig.ctl.mode, "history")
        self.assertEqual(rig.shown, rig.content(0, view=8))

    def test_enlarging_the_window_past_the_scroll_position_returns_to_live(self):
        rig = HistRig(size=(80, 6))
        rig.press(UP)                              # top 4; pencere 8 satır olunca canlı konum 2'ye iner
        rig.settle()
        rig.dims["size"] = (80, 9)
        rig.settle()
        self.assertEqual(rig.ctl.mode, "normal")
        self.assertIsNone(rig.shown)

    def test_a_tall_window_never_shows_more_rows_than_the_pane_has(self):
        rig = HistRig(rows=6, hist=100, size=(80, 30))
        rig.press(UP)
        rig.settle()
        self.assertEqual(len(rig.shown), 6)


class ErrorTests(unittest.TestCase):
    def test_an_error_shows_in_the_bar_and_leaves_the_old_page_alone(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        rig.history._results.append((-1, 9, None, "yuhem unreachable: timed out"))
        rig.settle()
        self.assertIn("✗ yuhem unreachable: timed out", rig.bar_text())
        self.assertEqual(rig.ctl.mode, "history")
        self.assertIsNone(rig.shown)

    def test_a_failed_page_is_not_asked_for_in_a_loop(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        rig.history._results.append((-1, 9, None, "boom"))
        rig.settle(10)
        self.assertEqual(len(rig.history.requests), 1)

    def test_any_key_is_a_retry(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        rig.history._results.append((-1, 9, None, "boom"))
        rig.settle()
        self.assertEqual(len(rig.history.requests), 1)
        rig.press("a")                    # sayfayı DEĞİŞTİRMEYEN, yok sayılan bir tuş bile yeniden dener
        self.assertEqual(len(rig.history.requests), 2)
        rig.press(UP)                     # sayfa değişince zaten yeni aralık istenir
        self.assertEqual(len(rig.history.requests), 3)

    def test_the_error_clears_when_a_page_arrives(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        rig.history._results.append((-1, 9, None, "boom"))
        rig.settle()
        rig.history._results.append((-1, 9, rig.history.payload(-1, 9), ""))
        rig.settle()
        self.assertNotIn("✗", rig.bar_text())
        self.assertEqual(rig.shown, rig.content(4))

    def test_a_control_character_in_an_error_never_reaches_the_bar(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        rig.history._results.append((-1, 9, None, "kötü\x1b[31m\nhata"))
        rig.settle()
        self.assertNotIn(ESC, rig.bar_text())
        self.assertNotIn("\n", rig.bar_text())

    def test_the_error_is_what_the_bar_shows_first_so_a_narrow_window_still_reads_it(self):
        rig = HistRig()
        rig.history.auto = False
        rig.press(UP)
        rig.history._results.append((-1, 9, None, "bu host'un paneli eski, geçmiş ucu yok"))
        rig.settle()
        text, style = rig.ctl.bar(80)
        self.assertIn("✗ bu host'un paneli eski, geçmiş ucu yok", text)
        self.assertLessEqual(watch.display_width(text), 80)      # 80 sütunda da sığar
        self.assertIn("End: canlı", text)
        self.assertNotIn("PgUp/PgDn", text)
        self.assertEqual(style, watch.STYLE_HISTORY)


class BarAndLifecycleTests(unittest.TestCase):
    def test_bar_shows_the_position_and_the_way_back(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        text, style = rig.ctl.bar(200)
        self.assertIn("GEÇMİŞ 1/105", text)
        self.assertIn("End/Esc/q canlı", text)
        self.assertEqual(style, watch.STYLE_HISTORY)
        self.assertNotIn("yükleniyor", text)
        rig.press(HOME)
        self.assertIn("GEÇMİŞ 105/105", rig.bar_text())

    def test_history_is_the_fast_tick_mode(self):
        rig = HistRig()
        rig.press(UP)
        self.assertEqual(rig.ctl.tick_seconds(), watch.INPUT_TICK_SECONDS)
        rig.press(END)
        self.assertEqual(rig.ctl.tick_seconds(), watch.TICK_SECONDS)

    def test_shutdown_leaves_history_and_closes_the_client(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        rig.ctl.shutdown()
        self.assertIsNone(rig.shown)
        self.assertTrue(rig.history.closed)

    def test_leaving_forgets_the_cache(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        rig.press(END)
        self.assertEqual(rig.ctl._h_lines, {})
        rig.history.requests.clear()
        rig.press(UP)
        self.assertEqual(rig.history.requests, [(-1, 9)])   # önbellek boş: yeniden istenir

    def test_live_frames_keep_arriving_without_touching_the_history_page(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        page = list(rig.shown)
        rig.live(text="yeni\ncanlı\nçıktı")
        rig.settle()
        self.assertEqual(rig.shown, page)

    def test_masked_state_still_tracks_live_frames_while_scrolled_back(self):
        rig = HistRig()
        rig.press(UP)
        rig.settle()
        rig.live(masked=True)
        rig.press(END)
        rig.press("iparola\r")
        self.assertEqual(rig.sender.sent, [])           # geçmişten dönünce de maskeli kapı çalışır


class BodyOverrideTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.out = io.StringIO()
        self.screen = watch.Screen(self.out, title="t", size_fn=lambda: (20, 5))
        self.viewer = watch.Viewer("yuhem", "s1", self.screen, clock=self.clock)
        self.viewer.apply_frame(good("canli1\ncanli2\ncanli3\ncanli4", cols=20, rows=4))

    def drawn(self):
        data = self.out.getvalue()
        self.out.truncate(0), self.out.seek(0)
        return data

    def test_override_replaces_the_live_body_and_clearing_restores_it(self):
        self.viewer.render()
        self.drawn()
        self.viewer.set_body_override(["gecmis1", "gecmis2"])
        self.viewer.render()
        data = self.drawn()
        self.assertIn("gecmis1", data)
        self.assertIn("gecmis2", data)
        self.assertNotIn("canli", data)
        self.viewer.set_body_override(None)
        self.viewer.render()
        self.assertIn("canli1", self.drawn())

    def test_an_unchanged_override_is_not_redrawn(self):
        self.viewer.set_body_override(["a", "b"])
        self.viewer.render()
        self.drawn()
        self.viewer.set_body_override(["a", "b"])
        self.viewer.render()
        self.assertEqual(self.drawn(), "")

    def test_override_lines_are_cut_to_the_width_and_the_height(self):
        self.viewer.set_body_override(["x" * 50] + [f"s{i}" for i in range(10)])
        self.viewer.render()
        data = self.drawn()
        self.assertIn("x" * 20, data)
        self.assertNotIn("x" * 21, data)
        self.assertNotIn("s5", data)          # gövde 4 satır

    def test_live_frames_do_not_overwrite_an_override(self):
        self.viewer.set_body_override(["gecmis"])
        self.viewer.render()
        self.drawn()
        self.viewer.apply_frame(good("yeni1\nyeni2\nyeni3\nyeni4", cols=20, rows=4))
        self.viewer.render()
        self.assertNotIn("yeni", self.drawn())

    def test_ansi_in_override_lines_is_kept(self):
        self.viewer.set_body_override([f"{ESC}[31mkirmizi{ESC}[0m"])
        self.viewer.render()
        self.assertIn(f"{ESC}[31mkirmizi", self.drawn())


# ── HistoryClient (gerçek HTTP) ───────────────────────────────────────────────────────────────

class GetPanel:
    """127.0.0.1'de gerçek bir HTTP sunucusu: geçmiş isteklerini kaydeder."""

    def __init__(self, token="tok", responder=None, delay=0.0):
        self.token, self.delay = token, delay
        self.responder = responder or (lambda q: (200, {"ok": True, "text": "a\nb", "start": int(q["start"][0]),
                                                        "end": int(q["end"][0]), "history_size": 7}))
        self.requests = []
        panel = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                auth = self.headers.get("Authorization")
                panel.requests.append({"path": parsed.path, "query": {k: v[0] for k, v in query.items()}, "auth": auth})
                if panel.delay:
                    time.sleep(panel.delay)
                status, obj = (401, {"ok": False}) if auth != f"Bearer {panel.token}" else panel.responder(query)
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


def wait_results(client, count, timeout=5.0):
    got, end = [], time.time() + timeout
    while len(got) < count and time.time() < end:
        got += client.take_results()
        time.sleep(0.005)
    return got


class HistoryClientTests(unittest.TestCase):
    def make(self, panel, token="tok", **kw):
        client = watch.HistoryClient(panel.port, "yuhem", "s1", read_token=lambda: token, **kw)
        self.addCleanup(client.close)
        return client

    def setUp(self):
        self.panel = GetPanel()
        self.addCleanup(self.panel.close)

    def test_request_shape_and_auth(self):
        client = self.make(self.panel)
        client.request(-30, -1)
        wait_results(client, 1)
        req = self.panel.requests[0]
        self.assertEqual(req["path"], "/api/term/history")
        self.assertEqual(req["query"], {"name": "s1", "host": "yuhem", "lang": "en", "start": "-30", "end": "-1"})
        self.assertEqual(req["auth"], "Bearer tok")

    def test_a_good_answer_is_delivered_with_its_range(self):
        client = self.make(self.panel)
        client.request(-30, -1)
        (start, end, payload, err), = wait_results(client, 1)
        self.assertEqual((start, end, err), (-30, -1, ""))
        self.assertEqual((payload["text"], payload["history_size"]), ("a\nb", 7))

    def test_ok_false_is_an_error_with_the_panels_message(self):
        panel = GetPanel(responder=lambda q: (200, {"ok": False, "error": "yuhem unreachable: timed out"}))
        self.addCleanup(panel.close)
        client = self.make(panel)
        client.request(0, 1)
        (_, _, payload, err), = wait_results(client, 1)
        self.assertEqual((payload, err), (None, "yuhem unreachable: timed out"))

    def test_an_old_remote_panel_without_the_endpoint_gets_a_helpful_message(self):
        panel = GetPanel(responder=lambda q: (404, {"error": "not found"}))
        self.addCleanup(panel.close)
        client = self.make(panel)
        client.request(0, 1)
        (_, _, payload, err), = wait_results(client, 1)
        self.assertIsNone(payload)
        self.assertEqual(err, "bu host'un paneli eski, geçmiş ucu yok")

    def test_wrong_token(self):
        client = self.make(self.panel, token="yanlis")
        client.request(0, 1)
        (_, _, payload, err), = wait_results(client, 1)
        self.assertIsNone(payload)
        self.assertIn("401", err)
        self.assertIn("web.token", err)

    def test_other_http_errors_and_garbage(self):
        for responder, want in ((lambda q: (500, {"ok": False}), "http 500"),
                                (lambda q: (200, b"<html>"), "panel JSON olmayan yanıt verdi"),
                                (lambda q: (200, {"ok": True, "text": "x"}), "panel reddetti"),              # start/history_size yok
                                (lambda q: (200, {"ok": True, "text": 5, "start": 0, "history_size": 1}), "panel reddetti")):
            panel = GetPanel(responder=responder)
            self.addCleanup(panel.close)
            client = self.make(panel)
            client.request(0, 1)
            (_, _, payload, err), = wait_results(client, 1)
            self.assertEqual((payload, err), (None, want))

    def test_panel_down(self):
        panel = GetPanel()
        port = panel.port
        panel.close()
        client = watch.HistoryClient(port, "yuhem", "s1", read_token=lambda: "tok")
        self.addCleanup(client.close)
        client.request(0, 1)
        (_, _, payload, err), = wait_results(client, 1)
        self.assertIsNone(payload)
        self.assertTrue(err)

    def test_unreadable_token_is_an_error_and_the_thread_survives(self):
        calls = iter([True, False])

        def token():
            if next(calls):
                raise watch.TransportError("web.token okunamadı", auth=True)
            return "tok"

        client = watch.HistoryClient(self.panel.port, "yuhem", "s1", read_token=token)
        self.addCleanup(client.close)
        client.request(0, 1)
        self.assertEqual(wait_results(client, 1)[0][2:], (None, "web.token okunamadı"))
        client.request(0, 1)
        self.assertIsNotNone(wait_results(client, 1)[0][2])

    def test_an_unexpected_exception_does_not_kill_the_worker(self):
        calls = []

        def urlopen(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("beklenmedik")
            raise OSError("kapali")

        client = watch.HistoryClient(1, "yuhem", "s1", read_token=lambda: "tok", urlopen=urlopen)
        self.addCleanup(client.close)
        client.request(0, 1)
        self.assertIn("iç hata", wait_results(client, 1)[0][3])
        client.request(0, 1)
        self.assertEqual(wait_results(client, 1)[0][3], "kapali")

    def test_the_latest_request_wins_while_one_is_in_flight(self):
        panel = GetPanel(delay=0.3)
        self.addCleanup(panel.close)
        client = self.make(panel)
        client.request(0, 9)                         # yola çıkar
        time.sleep(0.1)
        for start in (10, 20, 30, 40):               # bekleyen sürekli yenisiyle değişir
            client.request(start, start + 9)
        results = wait_results(client, 2, timeout=5)
        self.assertEqual([(r[0], r[1]) for r in results], [(0, 9), (40, 49)])
        self.assertEqual(len(panel.requests), 2)

    def test_busy_reflects_pending_and_in_flight_work(self):
        panel = GetPanel(delay=0.2)
        self.addCleanup(panel.close)
        client = self.make(panel)
        self.assertFalse(client.busy())
        client.request(0, 1)
        self.assertTrue(client.busy())
        wait_results(client, 1)
        end = time.time() + 2
        while client.busy() and time.time() < end:
            time.sleep(0.01)
        self.assertFalse(client.busy())

    def test_close_stops_the_worker_and_ignores_later_requests(self):
        client = self.make(self.panel)
        client.request(0, 1)
        wait_results(client, 1)
        client.close()
        client.request(5, 6)
        time.sleep(0.2)
        self.assertEqual(len(self.panel.requests), 1)

    def test_the_token_is_re_read_for_every_request(self):
        tokens = iter(["tok", "baska"])
        client = watch.HistoryClient(self.panel.port, "yuhem", "s1", read_token=lambda: next(tokens))
        self.addCleanup(client.close)
        client.request(0, 1)
        self.assertIsNotNone(wait_results(client, 1)[0][2])
        client.request(0, 1)
        self.assertIsNone(wait_results(client, 1)[0][2])


# ── uçtan uca: gerçek görüntüleyici süreci, kontrol terminali olan bir pty, sahte panel ───────

class ScrollPanel:
    """Sahte panel: canlı kare (pane 10 satır, 100 geçmiş) + sayfalı geçmiş ucu (içerik `H{no}`)."""

    ROWS, HIST = 10, 100

    def __init__(self, token="tok"):
        self.token = token
        self.history_requests = []
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
                parsed = urllib.parse.urlsplit(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                if self.headers.get("Authorization") != f"Bearer {panel.token}":
                    return self._reply(401, {"ok": False})
                if parsed.path == "/api/term/history":
                    panel.history_requests.append(q)
                    s, e = max(int(q["start"]), -panel.HIST), min(int(q["end"]), panel.ROWS - 1)
                    return self._reply(200, {"ok": True, "text": "\n".join(f"H{n}" for n in range(s, e + 1)),
                                             "start": s, "end": e, "history_size": panel.HIST, "rows": panel.ROWS,
                                             "cols": 40, "alternate_screen": False})
                live = "\n".join(f"live{n}" for n in range(panel.ROWS))
                self._reply(200, good(live, cols=40, rows=panel.ROWS, history_size=panel.HIST))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


_LAUNCH = ("import os, sys, fcntl, termios; os.setsid(); fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
           "os.execv(sys.executable, [sys.executable, '-m', 'claudeops', 'watch'] + sys.argv[1:])")


@unittest.skipIf(pty is None, "pty yok")
class ScrollProcessTests(unittest.TestCase):
    def setUp(self):
        self.panel = ScrollPanel()
        self.addCleanup(self.panel.close)
        self.workdir = tempfile.mkdtemp(prefix="cops_watch_scroll_")
        self.addCleanup(shutil.rmtree, self.workdir, True)
        with open(os.path.join(self.workdir, "web.token"), "w") as f:
            f.write("tok")
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 6, 60, 0, 0))   # gövde 5 satır
        env = dict(os.environ, CLAUDEOPS_DIR=self.workdir, TERM="xterm-256color", PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(
            [sys.executable, "-c", _LAUNCH, "local:x", "--port", str(self.panel.port), "--transport", "rest", "--no-resize"],
            stdin=slave, stdout=slave, stderr=slave, cwd=PY_DIR, env=env, close_fds=True)
        os.close(slave)
        self.buf, self.lock = bytearray(), threading.Lock()
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
        try:
            os.close(self.master)
        except OSError:
            pass

    def text(self):
        with self.lock:
            return bytes(self.buf).decode("utf-8", "replace")

    def wait_screen(self, needle, since=0, timeout=15.0):
        end = time.time() + timeout
        while time.time() < end:
            if needle in self.text()[since:]:
                return len(self.text())
            if self.proc.poll() is not None:
                break
            time.sleep(0.02)
        self.fail(f"ekranda {needle!r} görünmedi; son çıktı: {self.text()[-500:]!r}")

    def test_scroll_back_page_by_page_and_return_to_live(self):
        self.wait_screen("canlı")
        self.wait_screen("live9")
        m = len(self.text())
        os.write(self.master, UP.encode())
        self.wait_screen("GEÇMİŞ 1/105", since=m)
        self.wait_screen("H8", since=m)                         # canlı konum 5..9, bir satır yukarı: 4..8
        self.assertEqual(self.panel.history_requests[0]["start"], "-1")
        self.assertEqual(self.panel.history_requests[0]["end"], "9")
        self.assertEqual(self.panel.history_requests[0]["host"], "local")
        m = len(self.text())
        os.write(self.master, PGUP.encode())
        self.wait_screen("GEÇMİŞ 5/105", since=m)
        m = len(self.text())
        os.write(self.master, HOME.encode())
        self.wait_screen("GEÇMİŞ 105/105", since=m)
        self.wait_screen("H-100", since=m)
        m = len(self.text())
        os.write(self.master, END.encode())
        self.wait_screen("canlı", since=m)
        self.wait_screen("live9", since=m)
        self.assertIsNone(self.proc.poll())
        os.write(self.master, b"q")
        self.assertEqual(self.proc.wait(10), 0)

    def test_the_wheel_as_repeated_arrows_scrolls_and_q_returns_before_quitting(self):
        self.wait_screen("canlı")
        m = len(self.text())
        os.write(self.master, (UP * 3).encode())
        self.wait_screen("GEÇMİŞ 3/105", since=m)
        os.write(self.master, b"q")
        time.sleep(0.4)
        self.assertIsNone(self.proc.poll(), "geçmişteki q çıkış olmamalı")
        os.write(self.master, b"q")
        self.assertEqual(self.proc.wait(10), 0)


if __name__ == "__main__":
    unittest.main()

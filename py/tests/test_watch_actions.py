"""`py/cops watch` eylem kipi (`a`) ve satır sayacı testleri (TODO.md 2026-10-16).

Çalıştırma:  python3 -m unittest discover -s py/tests -p 'test_watch_actions.py' -v

Birim testler sahte koşturucu/saatle koşar (hiçbiri gerçekten beklemez); `ActionRunner` geçici kilit dizinine ve, uçtan uca
bir testte, 127.0.0.1'deki sahte bir panele bağlanır. Gerçek panele, tmux'a, kullanıcının terminaline DOKUNMAZ.
"""
import io
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claudeops import window_actions as wa  # noqa: E402
from claudeops.commands import watch  # noqa: E402
from test_window_actions import FakePanel, row, status  # noqa: E402

ESC = "\x1b"


def good(text="v1\nv2\nv3", cols=100, rows=3, **extra):
    base = {"ok": True, "text": text, "cols": cols, "rows": rows, "lite": True, "history_size": 0,
            "alternate_screen": False, "masked": False, "mode": None, "urls": [], "paths": []}
    base.update(extra)
    return base


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeSender:
    def submit(self, kind, payload):
        return 1

    def take_results(self):
        return []

    def close(self, wait=2.0):
        pass


class FakeRunner:
    """`ActionRunner` yerine: başlatılanları kaydeder, bitişi testin istediği anda verir."""

    def __init__(self):
        self.started, self.closed = [], False
        self._busy, self._done, self._progress = False, None, ("", "")

    def busy(self):
        return self._busy

    def start(self, action_id):
        if self._busy:
            return False
        self._busy = True
        self.started.append(action_id)
        self._progress = (wa.BY_ID[action_id].label, "başlıyor…")
        return True

    def progress(self):
        return self._progress if self._busy else ("", "")

    def take_result(self):
        done, self._done = self._done, None
        return done

    def finish(self, result):
        self._busy = False
        self._done = (self.started[-1], result)

    def close(self, wait=0.0):
        self.closed = True


class Rig:
    def __init__(self, host="yuhem", runner="fake", live=True, size=(100, 6), **frame_extra):
        self.clock = Clock()
        out = io.StringIO()
        self.screen = watch.Screen(out, title=f"{host}:s1", size_fn=lambda: size)
        self.out = out
        self.viewer = watch.Viewer(host, "s1", self.screen, clock=self.clock)
        self.runner = FakeRunner() if runner == "fake" else runner
        self.ctl = watch.InputController(self.viewer, FakeSender(), actions=self.runner, clock=self.clock)
        self.viewer.overlay = self.ctl.bar
        if live:
            self.viewer.apply_frame(good(**frame_extra))

    def press(self, *chunks):
        result = False
        for chunk in chunks:
            result = self.ctl.handle(chunk)
        return result

    def bar(self):
        return self.ctl.bar(100)

    def text(self):
        bar = self.ctl.bar(100)
        return bar[0] if bar else None

    def advance(self, seconds):
        self.clock.now += seconds


class ActionModeTests(unittest.TestCase):
    def test_a_non_destructive_letter_starts_the_action_at_once(self):
        for letter, action in (("h", "handover"), ("n", "newchat")):
            rig = Rig()
            rig.press("a")
            self.assertEqual(rig.ctl.mode, "actions")
            rig.press(letter)
            self.assertEqual(rig.runner.started, [action])
            self.assertEqual(rig.ctl.mode, "normal")

    def test_destructive_letters_wait_for_y(self):
        for letter, action in (("d", "stop"), ("y", "restart"), ("r", "reset")):
            rig = Rig()
            rig.press("a", letter)
            self.assertEqual(rig.ctl.mode, "confirm", letter)
            self.assertEqual(rig.runner.started, [], "onaydan ÖNCE başladı")
            rig.press("y")
            self.assertEqual(rig.runner.started, [action])
            self.assertEqual(rig.ctl.mode, "normal")

    def test_uppercase_letters_and_uppercase_confirm_work(self):
        rig = Rig()
        rig.press("a", "D", "Y")
        self.assertEqual(rig.runner.started, ["stop"])

    def test_anything_but_y_cancels_a_confirmation(self):
        for key in ("n", "\r", ESC, "x", "q", "a", " ", f"{ESC}[A"):
            rig = Rig()
            rig.press("a", "r", key)
            self.assertEqual((rig.ctl.mode, rig.runner.started), ("normal", []), repr(key))

    def test_a_pasted_y_never_confirms_and_a_pasted_a_never_opens_the_mode(self):
        rig = Rig()
        rig.press("a", "d", f"{ESC}[200~y{ESC}[201~")
        self.assertEqual(rig.runner.started, [])
        rig = Rig()
        rig.press(f"{ESC}[200~a{ESC}[201~")
        self.assertEqual(rig.ctl.mode, "normal")
        rig = Rig()
        rig.press("a", f"{ESC}[200~h{ESC}[201~")
        self.assertEqual((rig.ctl.mode, rig.runner.started), ("normal", []))

    def test_an_unknown_key_cancels_the_action_mode_and_the_next_letter_is_inert(self):
        rig = Rig()
        rig.press("a", "z")
        self.assertEqual(rig.ctl.mode, "normal")
        rig.press("h")                   # normal kipte `h` bir şey yapmaz
        self.assertEqual(rig.runner.started, [])
        rig.press("a", ESC)
        self.assertEqual(rig.ctl.mode, "normal")

    def test_the_modes_time_out_without_doing_anything(self):
        rig = Rig()
        rig.press("a")
        rig.advance(watch.ACTION_MODE_SECONDS + 0.1)
        rig.press("")
        self.assertEqual(rig.ctl.mode, "normal")
        rig.press("a", "d")
        rig.advance(watch.ACTION_CONFIRM_SECONDS + 0.1)
        rig.press("")
        self.assertEqual(rig.ctl.mode, "normal")
        rig.press("y")
        self.assertEqual(rig.runner.started, [])

    def test_the_menu_bar_lists_every_action_and_the_confirm_bar_names_the_target_and_the_consequence(self):
        rig = Rig()
        rig.press("a")
        text = rig.text()
        for a in wa.ACTIONS:
            self.assertIn(f"{a.key} {a.short}", text)
        self.assertEqual(rig.bar()[1], watch.STYLE_INPUT)
        rig.press("r")
        text, style = rig.bar()
        self.assertIn("Sıfırla: yuhem:s1?", text)
        self.assertIn("konuşma bir daha görünmez", text)
        self.assertIn("y: onayla", text)
        self.assertEqual(style, watch.STYLE_RAW)

    def test_a_local_target_is_shown_without_the_host_prefix(self):
        rig = Rig(host="local")
        rig.press("a", "d")
        self.assertIn("Durdur: s1?", rig.text())

    def test_without_a_runner_a_does_nothing_and_q_still_quits(self):
        rig = Rig(runner=None)
        rig.press("a")
        self.assertEqual(rig.ctl.mode, "normal")
        self.assertTrue(rig.press("q"))

    def test_the_hint_advertises_the_key(self):
        self.assertIn("a işlem", watch.INPUT_HINT)


class BusyTests(unittest.TestCase):
    def test_progress_replaces_the_bar_and_a_second_action_is_refused(self):
        rig = Rig()
        rig.press("a", "n")
        self.assertEqual(rig.text(), " … Yeni chat aç: başlıyor…")
        rig.press("a")
        self.assertEqual(rig.ctl.mode, "normal")                       # eylem kipi açılmadı
        self.assertEqual(rig.text(), " … Yeni chat aç: başlıyor…")      # çubuk hâlâ ilerlemeyi gösteriyor
        rig.press("a", "n")
        self.assertEqual(rig.runner.started, ["newchat"])               # ikinci başlatma denemesi yok sayıldı

    def test_q_does_not_quit_while_an_action_runs_because_it_would_strand_a_compound_action(self):
        rig = Rig()
        rig.press("a", "n")
        self.assertFalse(rig.press("q"))
        rig.runner.finish(wa.Result(True, "✓ yeni chat: s1_1"))
        rig.press("")
        self.assertTrue(rig.press("q"))      # bitti: çıkış serbest

    def test_the_result_is_flashed_long_enough_to_read_with_the_matching_colour(self):
        rig = Rig()
        rig.press("a", "n")
        rig.runner.finish(wa.Result(True, "✓ yeni chat: s1_1", name="s1_1"))
        rig.press("")
        self.assertEqual(rig.bar(), (" ✓ yeni chat: s1_1", watch.STYLE_LIVE))
        rig.advance(watch.ACTION_RESULT_SECONDS - 1)
        rig.press("")
        self.assertIsNotNone(rig.bar())
        rig.advance(2)
        rig.press("")
        self.assertIsNone(rig.bar())         # süre doldu: normal çubuk
        rig.press("a", "h")
        rig.runner.finish(wa.Result(False, "✗ handover: no_conversation"))
        rig.press("")
        self.assertEqual(rig.bar(), (" ✗ handover: no_conversation", watch.STYLE_SEVERE))

    def test_progress_does_not_hide_a_message_being_typed(self):
        rig = Rig()
        rig.press("a", "n")
        rig.press("i", "merhaba")
        self.assertIn("merhaba", rig.text())     # yazı satırı çubuğu, ilerleme değil

    def test_shutdown_lets_the_runner_finish_its_compound_action(self):
        rig = Rig()
        rig.ctl.shutdown()
        self.assertTrue(rig.runner.closed)


class GateTests(unittest.TestCase):
    def test_handover_is_blocked_on_a_masked_pane_but_nothing_else_is(self):
        rig = Rig(masked=True)
        rig.press("a", "h")
        self.assertEqual(rig.runner.started, [])
        self.assertIn("maskeli", rig.text())
        rig.press("a", "n")      # yeni chat panedeki girişe dokunmaz
        self.assertEqual(rig.runner.started, ["newchat"])

    def test_handover_needs_a_live_connection_but_a_gone_session_can_still_be_reset_or_renewed(self):
        rig = Rig(live=False)
        rig.press("a", "h")
        self.assertEqual(rig.runner.started, [])
        self.assertIn("canlı değil", rig.text())
        rig = Rig(live=False)
        rig.press("a", "n")
        self.assertEqual(rig.runner.started, ["newchat"])
        rig = Rig(live=False)
        rig.press("a", "r", "y")
        self.assertEqual(rig.runner.started, ["reset"])


class LinesCounterTests(unittest.TestCase):
    def status(self, **frame):
        rig = Rig(**frame)
        return rig.viewer.status()

    def test_count_sits_between_the_size_and_the_transport(self):
        rig = Rig(history_size=1542)
        rig.viewer.transport_name = "ws"
        text, _ = rig.viewer.status()
        self.assertIn("100×3 · 1542/2000 satır · ws", text)

    def test_amber_from_the_threshold_on_and_the_bar_style_is_restored_after_it(self):
        text, style = self.status(history_size=1900)
        self.assertIn(f"{watch.STYLE_WARN_TEXT}1900/2000 satır{style}", text)
        below, _ = self.status(history_size=1899)
        self.assertNotIn(watch.STYLE_WARN_TEXT, below)

    def test_threshold_follows_the_setting(self):
        rig = Rig(history_size=1500)
        rig.viewer.history_warn_at = 1500
        self.assertIn(watch.STYLE_WARN_TEXT, rig.viewer.status()[0])

    def test_escape_codes_do_not_widen_the_bar(self):
        text, _ = self.status(history_size=1950)
        self.assertEqual(watch.display_width(text), watch.display_width(text.replace(watch.STYLE_WARN_TEXT, "")))
        for cols in (30, 60, 140):       # kırpma ve dolgu kaçış dizilerini görünür genişliğe saymaz: çubuk tam `cols` olur
            drawn = watch.build_status(text, watch.STYLE_LIVE, cols, 6)
            self.assertEqual(watch.display_width(drawn), cols, cols)

    def test_hidden_on_the_alternate_screen_because_history_size_is_meaningless_there(self):
        text, _ = self.status(history_size=0, alternate_screen=True)
        self.assertNotIn("satır", text)

    def test_hidden_when_the_value_is_missing_or_not_a_count(self):
        for bad in (None, -1, "12", True, 3.5):
            text, _ = self.status(history_size=bad)
            self.assertNotIn("satır", text, repr(bad))

    def test_hidden_before_the_first_frame(self):
        rig = Rig(live=False)
        self.assertNotIn("satır", rig.viewer.status()[0])

    def test_warn_threshold_comes_from_settings_with_a_safe_fallback(self):
        with mock.patch("claudeops.settings.load_settings", return_value={"history_warn_at": 1800}):
            self.assertEqual(watch.history_warn_at(), 1800)
        for bad in (0, -5, "x", None, True):
            with mock.patch("claudeops.settings.load_settings", return_value={"history_warn_at": bad}):
                self.assertEqual(watch.history_warn_at(), watch.DEFAULT_HISTORY_WARN_AT, repr(bad))
        with mock.patch("claudeops.settings.load_settings", side_effect=OSError("disk")):
            self.assertEqual(watch.history_warn_at(), watch.DEFAULT_HISTORY_WARN_AT)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events = []
        patcher = mock.patch.object(watch, "diag_log", lambda event, **kw: self.events.append((event, kw)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def runner(self, run, **kw):
        return watch.ActionRunner(8765, "yuhem", "s1", read_token_fn=lambda: "t", run=run,
                                  lock_factory=lambda host, name: wa.ActionLock(host, name, directory=self.tmp.name), **kw)

    def wait_done(self, runner, timeout=5.0):
        end = threading.Event()
        for _ in range(int(timeout / 0.01)):
            done = runner.take_result()
            if done is not None:
                return done
            end.wait(0.01)
        self.fail("eylem bitmedi")

    def test_runs_in_the_background_reports_steps_and_hands_back_the_result_once(self):
        gate = threading.Event()
        seen = {}

        def run(client, action_id, host, name, on_step=None):
            seen.update(port=client.port, action=action_id, host=host, name=name)
            on_step("durduruluyor…")
            gate.wait(5)
            return wa.Result(True, "✓ ok", name="s1_1")

        r = self.runner(run)
        self.assertTrue(r.start("restart"))
        for _ in range(500):
            if r.progress()[1] == "durduruluyor…":
                break
            threading.Event().wait(0.01)
        self.assertEqual(r.progress(), ("Durdur + yeni isimle başlat", "durduruluyor…"))
        self.assertTrue(r.busy())
        self.assertFalse(r.start("stop"), "sürerken ikinci eylem başlamamalı")
        gate.set()
        action_id, result = self.wait_done(r)
        self.assertEqual((action_id, result.ok, result.name), ("restart", True, "s1_1"))
        self.assertEqual(seen, {"port": 8765, "action": "restart", "host": "yuhem", "name": "s1"})
        self.assertFalse(r.busy())
        self.assertIsNone(r.take_result())
        self.assertEqual([e for e, _ in self.events], ["watch_action_begin", "watch_action_end"])

    def test_a_lock_held_by_another_window_or_the_tmux_strip_refuses_without_running(self):
        called = []
        r = self.runner(lambda *a, **k: called.append(1) or wa.Result(True, "x"))
        held = wa.ActionLock("yuhem", "s1", directory=self.tmp.name)
        held.acquire()
        self.addCleanup(held.release)
        r.start("stop")
        _id, result = self.wait_done(r)
        self.assertFalse(result.ok)
        self.assertIn("başka bir pencere eylemi sürüyor", result.message)
        self.assertEqual(called, [])

    def test_a_crash_becomes_a_result_and_releases_the_lock(self):
        def boom(*a, **k):
            raise RuntimeError("kaboom")

        r = self.runner(boom)
        r.start("stop")
        _id, result = self.wait_done(r)
        self.assertFalse(result.ok)
        self.assertIn("iç hata: RuntimeError", result.message)
        again = wa.ActionLock("yuhem", "s1", directory=self.tmp.name)
        again.acquire()
        again.release()
        self.assertIn("watch_action_error", [e for e, _ in self.events])

    def test_close_waits_for_a_running_action(self):
        gate = threading.Event()
        r = self.runner(lambda *a, **k: (gate.wait(5), wa.Result(True, "ok"))[1])
        r.start("stop")
        threading.Timer(0.1, gate.set).start()
        r.close(wait=5)
        self.assertFalse(r._thread.is_alive())

    def test_end_to_end_against_a_fake_panel_a_restart_posts_stop_then_new_chat(self):
        panel = FakePanel(status([row("s1", host="yuhem", registered=True)]))
        self.addCleanup(panel.close)
        r = watch.ActionRunner(panel.port, "yuhem", "s1", read_token_fn=lambda: "test-token",
                               lock_factory=lambda host, name: wa.ActionLock(host, name, directory=self.tmp.name))
        r.start("restart")
        _id, result = self.wait_done(r)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(panel.paths(), ["/api/stop", "/api/new-chat"])
        self.assertEqual({b["host"] for _p, b in panel.posts()}, {"yuhem"})


if __name__ == "__main__":
    unittest.main()

"""22 Kas (cops dersi): (1) toparla/READY FOR HANDOVER direktifi paused projenin fazını AÇMAZ (keep_phase ya da metinden tanıma);
(2) sahip/CLI paused yapınca açık oturum idle_close'u (30 dk) beklemez: boştaysa devir+kapat, meşgulse tur bitince."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402


def _view(name, **kw):
    base = dict(running=True, cwd="/tmp/x", cli="claude", busy=False, history_size=100, tmux=True,
                started_at=1000.0, last_activity=1000.0)
    base.update(kw)
    return sw.SessionView(name=name, **base)


class WrapUpText(unittest.TestCase):
    def test_wrap_up_detected(self):
        self.assertTrue(sw.is_wrap_up_directive("Toparla: commit+push yap, sonra READY FOR HANDOVER yaz."))
        self.assertTrue(sw.is_wrap_up_directive("wrap up: commit, push, then READY FOR HANDOVER"))

    def test_plain_work_not_wrap_up(self):
        self.assertFalse(sw.is_wrap_up_directive("TODO 12'yi yap, test et."))
        self.assertFalse(sw.is_wrap_up_directive("READY FOR HANDOVER nedir?"))     # commit/push istemiyor

    def test_keep_phase_flag(self):
        self.assertTrue(sw.directive_keeps_phase("herhangi", {"keep_phase": True}))
        self.assertTrue(sw.directive_keeps_phase("commit+push, READY FOR HANDOVER", {}))
        self.assertFalse(sw.directive_keeps_phase("yeni iş", {}))


class PauseClose(unittest.TestCase):
    now = 100000.0

    def plan(self, view, phase="paused", req=True):
        projects = {"a": sw.Project(name="a", phase=phase, priority=1, cadence_minutes=60)}
        st = {"pause_close": {"a": self.now - 10}} if req else {}
        c = sw.Config(enabled=True)
        c.done_handover = True
        acts, st2 = sw.plan_tick([view], projects, st, c, self.now, [], [])
        return [a for a in acts if a.name == "a"], st2

    def test_idle_session_gets_handover_then_close(self):
        acts, st = self.plan(_view("a"))
        self.assertEqual([a.kind for a in acts], ["handover"])
        self.assertIn("a", st["ho_close"])
        self.assertNotIn("a", st.get("pause_close", {}))

    def test_busy_session_waits(self):
        acts, st = self.plan(_view("a", busy=True))
        self.assertEqual(acts, [])
        self.assertIn("a", st["pause_close"])

    def test_not_paused_anymore_clears(self):
        acts, st = self.plan(_view("a"), phase="planned")
        self.assertNotIn("handover", [a.kind for a in acts])
        self.assertNotIn("a", st.get("pause_close", {}))

    def test_no_request_no_action(self):
        acts, st = self.plan(_view("a"), req=False)
        self.assertNotIn("handover", [a.kind for a in acts])

    def test_gone_session_clears_request(self):
        acts, st = self.plan(_view("a", running=False))
        self.assertNotIn("a", st.get("pause_close", {}))

    def test_request_helper(self):
        st = {}
        sw.request_pause_close(st, "a", 5.0)
        self.assertEqual(st["pause_close"], {"a": 5.0})


if __name__ == "__main__":
    unittest.main()

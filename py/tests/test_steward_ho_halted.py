"""Devir gönderildikten SONRA proje paused/done olursa motor yeniden AÇMAZ (oiso 18:15, 2026-11-06).

Hata: `plan_tick` ho_pending döngüsü fazı hiç okumuyordu; devir giden proje sonradan `paused` yapılsa da READY FOR HANDOVER
(ya da oturum kapanışı) taze `--new` + yönerge açıyordu. Beklenen: paused/done -> `ho_halted` kaydı (yeniden açma/respawn YOK),
oturum devir notuyla açık kalır, ho_pending temizlenir; planned/planning davranışı DEĞİŞMEZ; ho_close (STEWARD-DONE kapanışı) aynı.
Saf (canlı oturum/tmux yok)."""
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


def _cfg():
    c = sw.Config(enabled=True)
    c.done_handover = False
    return c


class HoHaltedTest(unittest.TestCase):
    now = 100000.0

    def plan(self, phase, view, ho_close=None):
        projects = {"a": sw.Project(name="a", phase=phase, priority=1, cadence_minutes=60)}
        st = {"ho_pending": {"a": self.now - 60}}
        if ho_close:
            st["ho_close"] = {"a": self.now - 60}
        acts, st2 = sw.plan_tick([view], projects, st, _cfg(), self.now, [], [])
        return [a for a in acts if a.name == "a"], st2

    def test_paused_ready_no_respawn_session_stays(self):
        acts, st = self.plan("paused", _view("a", last_assistant="... READY FOR HANDOVER özet"))
        self.assertEqual([a.kind for a in acts], ["ho_halted"])
        self.assertEqual((acts[0].payload["phase"], acts[0].payload["step"]), ("paused", "ready"))
        self.assertNotIn("a", st["ho_pending"])

    def test_paused_session_gone_no_start(self):
        acts, st = self.plan("paused", _view("a", running=False))
        self.assertEqual([a.kind for a in acts], ["ho_halted"])
        self.assertEqual(acts[0].payload["step"], "gone")
        self.assertNotIn("a", st["ho_pending"])

    def test_done_ready_no_respawn(self):
        acts, st = self.plan("done", _view("a", last_assistant="READY FOR HANDOVER"))
        self.assertEqual([a.kind for a in acts], ["ho_halted"])
        self.assertNotIn("a", st["ho_pending"])

    def test_planned_unchanged_respawn_and_start(self):
        acts, _ = self.plan("planned", _view("a", last_assistant="READY FOR HANDOVER"))
        self.assertEqual([a.kind for a in acts], ["respawn"])
        acts, _ = self.plan("planned", _view("a", running=False))
        self.assertEqual([a.kind for a in acts], ["respawn"])

    def test_planning_unchanged(self):
        acts, _ = self.plan("planning", _view("a", last_assistant="READY FOR HANDOVER"))
        self.assertEqual([a.kind for a in acts], ["respawn"])

    def test_done_close_flow_still_stops(self):
        acts, st = self.plan("done", _view("a", last_assistant="READY FOR HANDOVER"), ho_close=True)
        self.assertEqual([a.kind for a in acts], ["stop"])

    def test_paused_busy_waits_then_halts(self):
        acts, st = self.plan("paused", _view("a", busy=True))
        self.assertEqual(acts, [])                       # meşgul: bekler (ho_pending korunur)
        self.assertIn("a", st["ho_pending"])


if __name__ == "__main__":
    unittest.main()

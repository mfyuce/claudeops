"""Aynı durmuş projenin iki cevaplı sorusu tek tick'te tek `start` üretir (uzops incelemesi R-13)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import steward as sw  # noqa: E402


class OneStartPerProject(unittest.TestCase):
    def _starts(self, phase):
        projects = {"alfa": sw.Project(name="alfa", phase=phase), "beta": sw.Project(name="beta", phase="planned")}
        qs = [sw.Question(id=i, project=p, text="hangi ad?", status="answered", answer="evet, aç", answered_at=1.0, created_at=0.5)
              for i, p in (("q1", "alfa"), ("q2", "alfa"), ("q3", "beta"))]
        cfg = sw.Config(enabled=True, max_active=2, max_starts_per_tick=2)
        acts, _ = sw.plan_tick([], projects, {}, cfg, 5000.0, qs, [])
        return acts

    def test_two_answers_one_start_and_slot_left_for_other_project(self):
        for phase in ("planned", "paused"):
            acts = self._starts(phase)
            self.assertEqual(sorted(a.name for a in acts if a.kind == "start"), ["alfa", "beta"], phase)
            self.assertLessEqual(len([a for a in acts if a.kind == "set_phase"]), 1, phase)


if __name__ == "__main__":
    unittest.main()

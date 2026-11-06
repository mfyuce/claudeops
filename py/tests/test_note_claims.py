"""Motor, beynin proje notundaki doğrulanabilir iddiaları (PID / kapıda bekliyor) doğrular (TBD#163 sonrası kalem 1). Gerçek süreç/git YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from test_steward import _cfg, _view  # noqa: E402


class TestClaims(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(sw.note_claims("koşu sürüyor, PID 4321; pid=77"), {"pids": [77, 4321], "gate": False})
        self.assertTrue(sw.note_claims("iş kapıda bekliyor")["gate"])
        self.assertEqual(sw.note_claims("bir şey yok"), {"pids": [], "gate": False})

    def test_dead_pid_and_empty_gate_are_contradictions(self):
        got = sw.check_note_claims("PID 99 sürüyor; kapıda bekliyor", lambda p: False, lambda: 0)
        self.assertEqual(len(got), 2)

    def test_alive_unknown_or_ahead_are_silent(self):
        self.assertEqual(sw.check_note_claims("PID 99; kapıda bekliyor", lambda p: True, lambda: 3), [])
        self.assertEqual(sw.check_note_claims("PID 99; kapıda bekliyor", lambda p: None, lambda: None), [])

    def test_contradiction_rides_the_idle_item_and_renders(self):
        projects = {"p1": sw.Project(name="p1", phase="planned", notes="PID 99 sürüyor")}
        v = _view("p1", busy=False, last_activity=1.0, started_at=1.0, last_assistant="x")
        items = sw.review_items([v], projects, _cfg(), 100000.0, [], [],
                                claim_check=lambda proj: sw.check_note_claims(projects[proj].notes, lambda p: False, lambda: None))
        self.assertEqual(len(items), 1)
        self.assertEqual(len(items[0]["contradictions"]), 1)
        self.assertIn("MOTOR ÇELİŞKİ", sw.build_tour_prompt(items))


if __name__ == "__main__":
    unittest.main()

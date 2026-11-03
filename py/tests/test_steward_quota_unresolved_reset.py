"""GATE-TODO3 #7 (steward_quota R-7): auto modda sifirlanma zamani cozulemezse tavan sessizce kapali kalmaz; neden gorunur.
Calistirma:  python3 py/tests/test_steward_quota_unresolved_reset.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import steward_quota as q  # noqa: E402


class UnresolvedResetTests(unittest.TestCase):
    def test_auto_without_reset_reports_reason_and_does_not_drain(self):
        d = q.decide({"mode": "auto"}, q.Usage(week_pct=50.0), 1_000_000.0)
        self.assertEqual(d.action, "ok")
        self.assertIsNone(d.cap)
        self.assertIn("çözülemedi", d.reason)

    def test_auto_without_reset_still_stops_at_final_limit(self):
        d = q.decide({"mode": "auto"}, q.Usage(week_pct=96.0), 1_000_000.0)
        self.assertEqual(d.action, "stop")

    def test_unparseable_reset_text_gives_none(self):
        self.assertIsNone(q._parse_reset("Foo 26, 5pm", "UTC", 1_000_000.0))
        self.assertIsNone(q._parse_reset("Oct 26, 5pm", "Yok/Zone", 1_000_000.0))

    def test_manual_mode_without_reset_has_no_unresolved_warning(self):
        d = q.decide({"mode": "manual", "manual_limit": "80"}, q.Usage(week_pct=50.0), 1_000_000.0)
        self.assertEqual(d.reason, "")


if __name__ == "__main__":
    unittest.main()

"""GATE-TODO 30-31: bilinmeyen ay adı None döner; manual modda manual_limit yokken day_* tavanı etkindir.

Çalıştırma:  python3 py/tests/test_quota_manual_and_month.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import steward_quota as sq  # noqa: E402

NOW = 1_700_000_000


class MonthTests(unittest.TestCase):
    def test_unknown_month_returns_none(self):
        self.assertIsNone(sq._parse_reset("Foo 26, 5:59pm", "UTC", NOW))

    def test_known_month_still_parses(self):
        self.assertIsNotNone(sq._parse_reset("Nov 26, 5:59pm", "UTC", NOW))


class ManualDayCapTests(unittest.TestCase):
    def _usage(self, pct):
        u = sq.Usage(week_pct=pct)
        u.reset_ts = NOW + 3 * 86400
        return u

    def test_manual_without_limit_honours_day_cap(self):
        u = self._usage(40.0)
        label = sq.day_label(u, NOW)
        d = sq.decide({"mode": "manual", "day_" + label: "30"}, u, NOW)
        self.assertEqual(d.action, "drain")

    def test_manual_without_limit_and_cap_is_ok(self):
        d = sq.decide({"mode": "manual"}, self._usage(40.0), NOW)
        self.assertEqual(d.action, "ok")


if __name__ == "__main__":
    unittest.main()

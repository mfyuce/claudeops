import unittest
from claudeops import steward


class OrphanDigestTest(unittest.TestCase):
    def test_line_shown_only_when_orphans(self):
        a = steward.daily_summary([], "2026-11-20", "tr", None, {"servers": 2, "procs": 3})
        self.assertIn("Sahipsiz kaynak: 2 yardımcı sunucu, 3 tanınmayan süreç", a)
        self.assertNotIn("Sahipsiz", steward.daily_summary([], "2026-11-20", "tr", None, {"servers": 0, "procs": 0}))
        self.assertNotIn("Sahipsiz", steward.daily_summary([], "2026-11-20", "tr"))
        self.assertIn("Orphaned resources: 1 helper", steward.daily_summary([], "2026-11-20", "en", None, {"servers": 1, "procs": 0}))


if __name__ == "__main__":
    unittest.main()

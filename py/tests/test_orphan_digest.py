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


class BrainTourRatioTest(unittest.TestCase):
    """D16: günlük özet beyin turu / skip / direktif sayısını ve skip oranını gösterir."""
    def test_ratio_line(self):
        d = "2026-11-20"
        es = [{"ts": d + "T10:00:00", "event": "tour"} for _ in range(4)] + [{"ts": d + "T10:01:00", "event": "skip"} for _ in range(3)] \
            + [{"ts": d + "T10:02:00", "event": "directive", "name": "a"}]
        tr = steward.daily_summary(es, d, "tr")
        self.assertIn("beyin turu: 4 tur, 3 skip (%75), 1 direktif", tr)
        self.assertIn("brain tours: 4 tours, 3 skips (%75), 1 directives", steward.daily_summary(es, d, "en"))
        self.assertNotIn("beyin turu", steward.daily_summary([], d, "tr"))

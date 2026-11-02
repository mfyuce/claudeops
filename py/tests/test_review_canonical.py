"""TBD#R3: tekilleştirmede kanonik kayıt (öncelik, yaş) sırasıyla seçilir; dict sırasına bağlı değil."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402


class CanonRankTest(unittest.TestCase):
    def r(self, state, at=0):
        return {"state": state, "created_at": at}

    def test_tiers(self):
        for good in ("verified", "approved", "exported"):
            self.assertLess(rv._canon_rank(self.r(good, 9)), rv._canon_rank(self.r("new", 1)))
        for bad in ("refuted", "rejected"):
            self.assertGreater(rv._canon_rank(self.r(bad, 1)), rv._canon_rank(self.r("new", 9)))

    def test_oldest_wins_within_tier(self):
        self.assertLess(rv._canon_rank(self.r("new", 1)), rv._canon_rank(self.r("new", 2)))
        self.assertLess(rv._canon_rank(self.r("verified", 1)), rv._canon_rank(self.r("approved", 2)))

    def test_bad_timestamp_is_tolerated(self):
        self.assertEqual(rv._canon_rank({"state": "new", "created_at": "x"}), (1, 0.0))
        self.assertEqual(rv._canon_rank({"state": "new"}), (1, 0.0))


if __name__ == "__main__":
    unittest.main()

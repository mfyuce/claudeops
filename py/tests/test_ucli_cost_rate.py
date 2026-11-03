"""ucli_cost.rate_usd_per_hour / rate_by_session: kayan pencere hızı (fiyat mantığı rv.usage_cost_usd'den; mutlak fiyat varsayılmaz)."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_cost  # noqa: E402

NOW = time.time()


def _rec(minutes_ago):
    return json.dumps({"t": (NOW - minutes_ago * 60) * 1000.0,
                       "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}}) + "\n"


class RateTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        with open(os.path.join(self.d.name, "a.jsonl"), "w") as f:
            f.write(_rec(10) + _rec(50) + _rec(200))     # 200 dk önce: hiçbir pencereye girmez

    def test_window_scales_rate(self):
        r60 = ucli_cost.rate_usd_per_hour(NOW, 60.0, self.d.name)
        r15 = ucli_cost.rate_usd_per_hour(NOW, 15.0, self.d.name)
        self.assertGreater(r60, 0)
        self.assertAlmostEqual(r15 / r60, 2.0, places=6)    # 15 dk: 1 istek -> 4c; 60 dk: 2 istek -> 2c

    def test_per_session_sums_to_total(self):
        with open(os.path.join(self.d.name, "b.jsonl"), "w") as f:
            f.write(_rec(5))
        by = ucli_cost.rate_by_session(NOW, 60.0, self.d.name)
        self.assertEqual(set(by), {"a", "b"})
        self.assertAlmostEqual(sum(by.values()), ucli_cost.rate_usd_per_hour(NOW, 60.0, self.d.name))

    def test_corrupt_lines_are_skipped(self):
        with open(os.path.join(self.d.name, "c.jsonl"), "w") as f:
            f.write("{bozuk\n[]\n\n" + _rec(5))
        by = ucli_cost.rate_by_session(NOW, 60.0, self.d.name)
        self.assertIn("c", by)
        self.assertGreater(by["c"], 0)

    def test_missing_dir_and_bad_window(self):
        self.assertEqual(ucli_cost.rate_usd_per_hour(NOW, 60.0, os.path.join(self.d.name, "yok")), 0.0)
        self.assertEqual(ucli_cost.rate_by_session(NOW, 0, self.d.name), {})
        self.assertEqual(ucli_cost.rate_by_session(NOW, "x", self.d.name), {})


if __name__ == "__main__":
    unittest.main()

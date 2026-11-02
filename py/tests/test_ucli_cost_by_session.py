"""ucli_cost.state: oturum (kodcu) başı bugünkü $ dökümü (P4-2 harcama paneli) — stdlib unittest."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_cost  # noqa: E402


class TestBySession(unittest.TestCase):
    def setUp(self):
        ucli_cost.invalidate()
        self.addCleanup(ucli_cost.invalidate)

    def test_breakdown_sorted_and_total_matches(self):
        cfg = {"daily_cap_usd": 10, "cache_ttl": "1h"}
        by = {"coder-a": 0.5, "coder-b": 2.25, "idle": 0.0}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ucli_cost, "ucli_cost_config", lambda: cfg), \
                mock.patch.object(ucli_cost, "per_session_usd", return_value=by):
            st = ucli_cost.state(base=d)
        self.assertEqual([s["session"] for s in st["by_session"]], ["coder-b", "coder-a"])  # 0 olan yok, çoktan aza
        self.assertAlmostEqual(st["today_usd"], 2.75)
        self.assertEqual(st["pct"], 27.5)

    def test_top_n_limit(self):
        cfg = {"daily_cap_usd": 0, "cache_ttl": "5m"}
        by = {f"s{i:02d}": float(i + 1) for i in range(ucli_cost.BY_SESSION_TOP + 5)}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ucli_cost, "ucli_cost_config", lambda: cfg), \
                mock.patch.object(ucli_cost, "per_session_usd", return_value=by):
            st = ucli_cost.state(base=d)
        self.assertEqual(len(st["by_session"]), ucli_cost.BY_SESSION_TOP)
        self.assertIsNone(st["pct"])

    def test_per_session_reads_files(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "x.jsonl"), "w").close()
            open(os.path.join(d, "note.txt"), "w").close()
            with mock.patch.object(ucli_cost.rv, "usage_cost_usd", return_value=1.5):
                got = ucli_cost.per_session_usd(base=d)
                self.assertEqual(got, {"x": 1.5})
                self.assertEqual(ucli_cost.today_usd(base=d), 1.5)
        self.assertEqual(ucli_cost.per_session_usd(base="/nonexistent-dir-xyz"), {})


if __name__ == "__main__":
    unittest.main()

"""Reviewer koşu süresi: runs kaydına `seconds`, tüm sağlayıcılar için `duration_summary` (stdlib unittest)."""
import tempfile
import unittest
from unittest import mock

from claudeops import review as rv
from claudeops import steward as sw


class DurationTest(unittest.TestCase):
    def test_run_seconds(self):
        self.assertEqual(rv._run_seconds({"started_at": 100.0, "finished_at": 142.04}), 42.0)
        self.assertIsNone(rv._run_seconds({"finished_at": 5.0}))
        self.assertIsNone(rv._run_seconds({"started_at": 10.0, "finished_at": 5.0}))
        self.assertIsNone(rv._run_seconds({"started_at": "x", "finished_at": 5.0}))

    def test_update_pair_records_seconds_in_runs(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sw, "STEWARD_DIR", d):
            p = sw.paths_for("reviewer")
            t = rv.ReviewTarget("claude", "m1", "m1")
            rv.update_pair(p, "proj", t, status="running", started_at=100.0)
            rv.update_pair(p, "proj", t, status="done", finished_at=130.0, file="/x.md")
            runs = rv.load_history(p)["runs"]
            self.assertEqual(runs[-1]["seconds"], 30.0)

    def test_duration_summary(self):
        h = {"runs": [
            {"pair": "a|claude/m", "seconds": 30.0}, {"pair": "a|claude/m", "seconds": 12.5},
            {"pair": "a|claude/m"},                                    # eski kayıt: süre yok -> bilinmiyor
            {"pair": "b|codex/x", "seconds": 100}, {"pair": "bozuk"}, {"pair": "a|agy/y", "seconds": True}]}
        rows = rv.duration_summary(h)
        self.assertEqual([(r["project"], r["target"], r["runs"], r["seconds"], r["unknown"]) for r in rows],
                         [("b", "codex/x", 1, 100.0, 0), ("a", "claude/m", 3, 42.5, 1), ("a", "agy/y", 1, 0.0, 1)])
        self.assertEqual(len(rv.duration_summary(h, "a")), 2)
        self.assertEqual(rv.duration_summary(None), [])


if __name__ == "__main__":
    unittest.main()

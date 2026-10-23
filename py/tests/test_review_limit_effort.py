import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import review as rv  # noqa: E402


class TestEffortAndLimit(unittest.TestCase):
    def test_path_has_effort_layer(self):
        t = rv.ReviewTarget("claude", "claude-haiku-4-5", "claude-haiku-4-5")
        p = rv.review_path("/r", "ncs", t, "20261024120000", "low")
        self.assertEqual(p, "/r/ncs/claude/claude-haiku-4-5/low/20261024120000.md")
        self.assertEqual(rv.review_path("/r", "ncs", t, "20261024120000"), "/r/ncs/claude/claude-haiku-4-5/20261024120000.md")

    def test_effort_for(self):
        cfg = types.SimpleNamespace(review_claude_effort="high")
        self.assertEqual(rv.effort_for(cfg, "claude"), "high")
        self.assertEqual(rv.effort_for(cfg, "evren"), "default")

    def test_daily_limit_detect_and_midnight(self):
        self.assertTrue(rv.is_daily_limit("x", '{"code":"daily_token_limit_exceeded"}'))
        self.assertFalse(rv.is_daily_limit("token_rate_limit_exceeded"))
        self.assertEqual(rv.next_utc_midnight(86400 * 3 + 5), 86400 * 4)

    def test_blocked_mode_skipped_by_planner(self):
        ev = rv.ReviewTarget("evren", "m", "m")
        cl = rv.ReviewTarget("claude", "c", "c")
        pool = {"projects": {"p": {"enabled": True}}}
        hist = {"pairs": {}, "blocks": {"evren": {"until": 100.0}}}
        self.assertEqual(rv.next_review(pool, hist, [ev, cl], 50.0), ("p", cl))
        self.assertEqual(rv.next_review(pool, hist, [ev, cl], 150.0), ("p", ev))


if __name__ == "__main__":
    unittest.main()

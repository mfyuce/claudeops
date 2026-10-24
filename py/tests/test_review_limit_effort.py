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
        self.assertEqual(p, "/r/ncs/claude/claude-haiku-4-5/low/20261024120000/20261024120000.md")
        self.assertEqual(rv.review_path("/r", "ncs", t, "20261024120000"), "/r/ncs/claude/claude-haiku-4-5/20261024120000/20261024120000.md")

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

    AGY_ERR = ('AGY_ERROR: {"short_error":"RESOURCE_EXHAUSTED (code 429): Individual quota reached. Please upgrade your '
               'subscription to increase your limits. Resets in 107h49m47s.","status":"RESOURCE_EXHAUSTED","error_code":429}')

    def test_agy_model_quota_parse(self):
        self.assertTrue(rv.is_quota_exhausted("x", self.AGY_ERR))
        self.assertFalse(rv.is_quota_exhausted("token_rate_limit_exceeded", "timeout"))
        self.assertEqual(rv.reset_seconds(self.AGY_ERR), 107 * 3600 + 49 * 60 + 47)
        self.assertEqual(rv.reset_seconds("Resets in 2d3h"), 2 * 86400 + 3 * 3600)
        self.assertEqual(rv.reset_seconds("resets in 12m30s"), 750)
        self.assertEqual(rv.reset_seconds("resets in 9999d"), rv.QUOTA_MAX_SECONDS)       # saçma süre kırpılır
        self.assertIsNone(rv.reset_seconds("quota reached, try later"))
        self.assertEqual(rv.quota_block_until(1000.0, "quota reached"), 1000.0 + rv.QUOTA_FALLBACK_SECONDS)
        self.assertEqual(rv.quota_block_until(1000.0, "x", self.AGY_ERR), 1000.0 + 107 * 3600 + 49 * 60 + 47)

    def test_model_block_only_removes_that_model(self):
        a1 = rv.ReviewTarget("agy", "claude-opus-5-5-high", "claude-opus-5-5-high")
        a2 = rv.ReviewTarget("agy", "gemini-4-argon-medium", "gemini-4-argon-medium")
        pool = {"projects": {"p": {"enabled": True}}}
        hist = {"pairs": {}, "blocks": {a1.key: {"until": 1000.0}}}
        self.assertEqual(rv.next_review(pool, hist, [a1, a2], 50.0), ("p", a2))        # opus bloklu, argon sürer
        self.assertIsNone(rv.next_review(pool, hist, [a1], 50.0))
        self.assertEqual(rv.next_review(pool, hist, [a1], 1500.0), ("p", a1))          # süre dolunca geri gelir


if __name__ == "__main__":
    unittest.main()

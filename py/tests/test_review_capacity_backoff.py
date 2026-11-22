"""Evren 429/503 geçici sıkışıklık: deneme hakkı yanmaz, retry_at'a dek sıra başka çifte geçer, sınırdan sonra normal sayılır."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402

NOW = 1_800_000_000.0
T = rv.ReviewTarget("evren", "glm-5.3", "glm-5.3")


def _pool():
    return {"projects": {"p": {"enabled": True, "source": "auto", "added_at": 1, "removed_at": None}}}


def _hist(**rec):
    base = {"status": "error", "started_at": NOW - 600, "finished_at": NOW - 500, "attempts": 1}
    base.update(rec)
    return {"version": 1, "pairs": {rv.pair_key("p", T): base}, "runs": []}


class CapacityBackoffTests(unittest.TestCase):
    def test_detect_and_retry_after(self):
        self.assertTrue(rv.is_capacity_error("HTTP 503 model_capacity_exhausted"))
        self.assertFalse(rv.is_capacity_error("syntax error"))
        self.assertEqual(rv.capacity_retry_seconds("x"), rv.CAPACITY_RETRY_MIN)
        self.assertEqual(rv.capacity_retry_seconds("Retry-After: 900"), 900.0)
        self.assertEqual(rv.capacity_retry_seconds("retry-after: 99999"), rv.CAPACITY_RETRY_MAX)

    def test_capacity_error_does_not_consume_attempt(self):
        rec = {"error": "capacity: sıkışık", "attempts": 1}
        self.assertFalse(rv.counts_as_attempt(rec))
        self.assertTrue(rv.counts_as_attempt({"error": "capacity: x", "attempts": rv.CAPACITY_MAX_TRIES + 1}))

    def test_waits_until_retry_at_then_retries(self):
        h = _hist(error="capacity: x", retry_at=NOW + 300)
        self.assertIsNone(rv.next_review(_pool(), h, [T], NOW))
        h = _hist(error="capacity: x", retry_at=NOW - 1)
        self.assertEqual(rv.next_review(_pool(), h, [T], NOW), ("p", T))

    def test_plain_error_still_locked_for_evren(self):
        self.assertIsNone(rv.next_review(_pool(), _hist(error="timeout 20 dk"), [T], NOW))


if __name__ == "__main__":
    unittest.main()

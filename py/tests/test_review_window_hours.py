"""review_window_hours -> next_review(window=...): kısa pencerede bitmiş çift yeniden aday; HEAD aynıysa yine değil."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402

NOW = 1_800_000_000.0
T = rv.ReviewTarget("agy", "gemini-3-flash", "gemini-3-flash")


def _pool():
    return {"projects": {"p": {"enabled": True, "source": "auto", "added_at": 1, "removed_at": None}}}


def _hist(age_hours, head="h1"):
    rec = {"status": "done", "started_at": NOW - age_hours * 3600 - 60,
           "finished_at": NOW - age_hours * 3600, "attempts": 1, "head": head}
    return {"version": 1, "pairs": {rv.pair_key("p", T): rec}, "runs": []}


class ReviewWindowHoursTests(unittest.TestCase):
    def test_window_seconds_conversion_and_fallback(self):
        self.assertEqual(rv.window_seconds(12), 12 * 3600.0)
        self.assertEqual(rv.window_seconds(720), 30 * 86400.0)
        for bad in (0, -5, "x", None):
            self.assertEqual(rv.window_seconds(bad), float(rv.WINDOW_SECONDS))

    def test_default_window_keeps_pair_fresh(self):
        self.assertIsNone(rv.next_review(_pool(), _hist(13), [T], NOW, window=rv.window_seconds(720)))

    def test_short_window_makes_pair_due_again(self):
        got = rv.next_review(_pool(), _hist(13), [T], NOW, window=rv.window_seconds(12))
        self.assertEqual(got, ("p", T))

    def test_same_head_still_skipped_with_short_window(self):
        got = rv.next_review(_pool(), _hist(13, "h1"), [T], NOW, window=rv.window_seconds(12), head_of=lambda p: "h1")
        self.assertIsNone(got)
        got = rv.next_review(_pool(), _hist(13, "h1"), [T], NOW, window=rv.window_seconds(12), head_of=lambda p: "h2")
        self.assertEqual(got, ("p", T))


if __name__ == "__main__":
    unittest.main()

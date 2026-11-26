"""TBD#368 (b): sonlu olmayan sayı (Infinity, NaN, float'a sığmayan tam sayı) bozuk kayıttır; atlanıp loglanır,
planlayıcı/özet/maliyet düşmez. Geçici dizin; ağ yok. Çalıştırma: python3 -m unittest discover -s py/tests"""
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_review_bad_records import _Logged, _tmp_paths, T  # noqa: E402
from claudeops import review  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402

BAD = (float("inf"), float("-inf"), float("nan"), 10 ** 400, "inf", "nan")


class NonFiniteNumberTest(_Logged):
    def test_num_returns_default(self):
        for bad in BAD:
            self.assertEqual(review._num(bad), 0.0, bad)
        self.assertIn("number.nonfinite", self.whats())

    def test_counts_as_attempt_survives_attempts(self):
        for bad in BAD:
            rec = {"error": review.CAPACITY_ERROR_PREFIX + " x", "attempts": bad}
            self.assertIn(review.counts_as_attempt(rec), (True, False))

    def test_planner_and_update_pair_survive(self):
        paths = _tmp_paths(self.dir)
        for bad in BAD:
            rec = {"status": "error", "attempts": bad, "started_at": 100.0}
            hist = {"pairs": {review.pair_key("p", T): rec}, "runs": []}
            review.next_review({"projects": {"p": {"enabled": True}}}, hist, [T], 200.0)
            review.save_history(paths, hist)
            new = review.update_pair(paths, "p", T, status="running", started_at=200.0)
            self.assertEqual(new["attempts"], 1, bad)

    def test_field_treats_as_bad(self):
        base = {"state": "verify_sent", "verify_session": "s", "verify_sent_at": 1}
        data = {str(i): dict(base, verify_sent_at=bad) for i, bad in enumerate(BAD)}
        data["ok"] = dict(base)
        self.assertEqual(review.requeue_stale_verify(data, 10 ** 9), ["ok"])
        self.assertEqual(review.blocked_modes({"blocks": {"evren": {"until": float("inf")}}}, 1.0), [])
        self.assertIn("blocks.until", self.whats())

    def test_pid_tree_ignores_infinite_pid(self):
        self.assertEqual(wr._pid_tree(float("inf")), [])

    def test_run_seconds(self):
        for bad in BAD:
            self.assertIsNone(review._run_seconds({"started_at": 5.0, "finished_at": bad}), bad)

    def test_duration_summary(self):
        runs = [{"pair": "p|evren/m", "seconds": s} for s in (2.0, float("inf"), float("nan"), 10 ** 400)]
        row = review.duration_summary({"runs": runs})[0]
        self.assertEqual((row["runs"], row["timed"], row["unknown"], row["seconds"]), (4, 1, 3, 2.0))
        self.assertIn("runs.seconds", self.whats())

    def test_usage_cost_skips_bad_line(self):
        path = os.path.join(self.dir, "u.usage.jsonl")
        good = {"t": 1, "usage": {"input_tokens": 1000000}}
        bad = [{"t": b, "usage": {"input_tokens": 5}} for b in BAD]
        bad += [{"t": 1, "usage": {"input_tokens": b}} for b in BAD[:4]]
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(good) + "\n")
        base = review.usage_cost_usd(path, "sonnet-5-5")
        with open(path, "a", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in bad))
        cost = review.usage_cost_usd(path, "sonnet-5-5")
        self.assertTrue(math.isfinite(cost))
        self.assertAlmostEqual(cost, base, places=6)
        self.assertIn("usage.record", self.whats())


if __name__ == "__main__":
    unittest.main()

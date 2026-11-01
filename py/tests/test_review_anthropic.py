import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import json, os, tempfile, types, unittest
from claudeops import review as rv


class TestAnthropicCost(unittest.TestCase):
    def _usage(self, d, model, rows):
        path = os.path.join(d, "reviews", "copsdev", "anthropic", model, "high", "20261031000000", "20261031000000.usage.jsonl")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            for u in rows:
                f.write(json.dumps({"event": "request", "usage": u}) + "\n")
        return path

    def test_cost_ucli_format(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._usage(d, "claude-sonnet-5-5", [{"prompt_tokens": 1_000_000, "cached_tokens": 400_000, "completion_tokens": 100_000}])
            # 600K yeni x2,5 + 400K okuma x0,1 (Sonnet 5.5 0,05x) + 100K cikti x10 = 1,5 + 0,04 + 1,0
            self.assertAlmostEqual(rv.usage_cost_usd(f, "claude-sonnet-5-5"), 2.54, places=4)
            self.assertAlmostEqual(rv.anthropic_spent_usd(os.path.join(d, "reviews")), 2.54, places=4)

    def test_unknown_model_priced_as_opus(self):
        self.assertEqual(rv.anthropic_price("claude-x-9"), rv.ANTHROPIC_PRICES["opus-5-5"])
        self.assertEqual(rv.anthropic_price("claude-fable-5-1"), rv.ANTHROPIC_PRICES["fable-5-1"])
        self.assertGreater(rv.anthropic_price("claude-fable-5-1")[0], rv.anthropic_price("claude-opus-5-5")[0])

    def test_targets_and_attempts(self):
        cfg = types.SimpleNamespace(review_anthropic_models="claude-haiku-5-5@low,claude-haiku-5-5@max", review_claude_models="",
                                    review_codex_models="", review_copilot_models="", review_agy_models="", review_evren_models="")
        ts = rv.targets_from_config(cfg, [], [])
        self.assertEqual([(t.mode, t.effort) for t in ts], [("anthropic", "low"), ("anthropic", "max")])
        self.assertEqual(rv.max_attempts("anthropic"), 1)


class TestTrialComplete(unittest.TestCase):
    def test_one_shot(self):
        from claudeops.commands import web_review as wr
        t = rv.ReviewTarget("anthropic", "claude-haiku-5-5", "claude-haiku-5-5", "low")
        cfg = types.SimpleNamespace(review_anthropic_projects="copsdev")
        pend = {"pairs": {}}
        done = {"pairs": {rv.pair_key("copsdev", t): {"status": "done", "finished_at": 1}}}   # pencere (30 gün) çoktan geçmiş olsa da
        self.assertFalse(wr.anthropic_trial_complete(cfg, {}, pend, [t]))
        self.assertTrue(wr.anthropic_trial_complete(cfg, {}, done, [t]))
        self.assertEqual(wr.anthropic_filter(types.SimpleNamespace(reviews="/nonexistent"), cfg, [t], {}, done), [])

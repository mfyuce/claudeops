import types
import unittest
from unittest import mock

from claudeops import review as rv

CAT = {"claude-fable-5-1": "disabled", "claude-fable-5-2": "enabled", "claude-opus-5-5": "enabled"}


def _cfg(**kw):
    base = dict(review_claude_models="", review_claude_auth="api", review_codex_models="", review_copilot_models="",
                review_anthropic_models="", review_agy_models="", review_evren_models="", review_excluded="")
    base.update(kw)
    return types.SimpleNamespace(**base)


class ClaudeSubscriptionTargets(unittest.TestCase):
    def test_api_empty_is_off(self):
        self.assertEqual(rv.claude_specs(_cfg(), CAT), [])

    def test_subscription_empty_uses_catalog_fable_levels(self):
        self.assertEqual(rv.claude_specs(_cfg(review_claude_auth="subscription"), CAT),
                         ["claude-fable-5-2@low", "claude-fable-5-2@medium", "claude-fable-5-2@high"])

    def test_manual_list_drops_disabled(self):
        c = _cfg(review_claude_models="claude-fable-5-1@low,claude-opus-5-5@low")
        self.assertEqual(rv.claude_specs(c, CAT), ["claude-opus-5-5@low"])

    def test_targets_from_config_subscription(self):
        with mock.patch.object(rv, "claude_catalog", return_value=CAT):
            ts = rv.targets_from_config(_cfg(review_claude_auth="subscription"), [], [])
        self.assertEqual([(t.mode, t.model, t.effort) for t in ts],
                         [("claude", "claude-fable-5-2", e) for e in ("low", "medium", "high")])


if __name__ == "__main__":
    unittest.main()

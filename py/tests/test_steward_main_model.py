"""Sahip kuralı 18 Kas 2026: değnekçinin açtığı claude ana oturumu kayıtlı model ne olursa olsun Sonnet + medium."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402

S = "claude-sonnet-5-5"


class MainSessionModel(unittest.TestCase):
    def test_registered_fable_becomes_sonnet_medium(self):
        self.assertEqual(sw.main_session_model_effort("claude-fable-5-1", "high", "claude", S), (S, "medium"))

    def test_opus_and_empty_on_claude(self):
        self.assertEqual(sw.main_session_model_effort("claude-opus-5-5", "", "claude", S), (S, "medium"))
        self.assertEqual(sw.main_session_model_effort("", "", "claude", S), (S, "medium"))

    def test_non_claude_cli_untouched(self):
        self.assertEqual(sw.main_session_model_effort("gemini-3-pro-high", "high", "agy", S), ("gemini-3-pro-high", "high"))
        self.assertEqual(sw.main_session_model_effort("", "", "codex", S), ("", ""))

    def test_remote_unknown_cli_only_claude_models(self):
        self.assertEqual(sw.main_session_model_effort("claude-fable-5-1", "high", "", S), (S, "medium"))
        self.assertEqual(sw.main_session_model_effort("glm-5.3", "high", "", S), ("glm-5.3", "high"))
        self.assertEqual(sw.main_session_model_effort("", "", "", S), ("", ""))

    def test_non_claude_model_on_claude_cli_untouched(self):
        self.assertEqual(sw.main_session_model_effort("glm-5.3", "high", "claude", S), ("glm-5.3", "high"))

    def test_no_sonnet_known_is_noop(self):
        self.assertEqual(sw.main_session_model_effort("claude-fable-5-1", "high", "claude", ""), ("claude-fable-5-1", "high"))


if __name__ == "__main__":
    unittest.main()

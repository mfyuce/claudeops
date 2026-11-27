"""Sahip kuralı 18 Kas 2026: değnekçinin açtığı claude ana oturumu kayıtlı model ne olursa olsun ana oturum modeli + medium.
Ana oturum modeli 18 Kas'ta en yeni Sonnet'ti; 28 Kas 2026'dan beri Ayarlar'daki claude varsayılanı, o boşsa Opus. Saf
`main_session_model_effort` testlerinde `S` yalnız "verilen ana model" yerine geçer."""
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


class MainModelFromSettings(unittest.TestCase):
    """Sahip kararı 28 Kas 2026 ("opus yapalım, ben tersini söyleyene kadar"): değnekçinin açtığı claude ana oturumu
    Ayarlar'daki `default_model.claude` (geçerliyse), boşsa Opus; effort `medium`. Ayarlar'dan geri alınabilir."""
    CHOICES = ["claude-fable-5-1", "claude-haiku-5-5", "claude-opus-5", "claude-opus-5-5", "claude-sonnet-5-5"]

    def setUp(self):
        import tempfile
        from unittest import mock
        from claudeops import settings
        from claudeops.commands import web_steward as ws
        from claudeops.providers import get_provider
        self.settings, self.ws = settings, ws
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        prov = type(get_provider("claude"))
        for p in (mock.patch.object(settings, "SETTINGS_JSON", os.path.join(d.name, "settings.json")),
                  mock.patch.object(prov, "model_choices", lambda _s: list(self.CHOICES)),
                  mock.patch.object(ws, "_project_cli", lambda name: "claude"),
                  mock.patch.object(sw, "log_event", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)

    def _main(self, **proj):
        return self.ws._main_model_effort(sw.Project(name="p", phase="planned", **proj), sw.Config(), "p")

    def test_empty_setting_gives_opus_medium(self):
        self.assertEqual(self._main(), ("claude-opus-5-5", "medium"))
        self.assertEqual(self._main(model="claude-fable-5-1", effort="high"), ("claude-opus-5-5", "medium"))
        self.assertEqual(self._main(model="claude-sonnet-5-5", effort="medium"), ("claude-opus-5-5", "medium"))

    def test_setting_wins_and_can_revert_to_sonnet(self):
        self.settings.save_settings({"default_model": {"claude": "claude-sonnet-5-5"}})
        self.assertEqual(self._main(model="claude-opus-5-5"), ("claude-sonnet-5-5", "medium"))

    def test_invalid_setting_falls_back_to_opus(self):
        self.settings.save_settings({"default_model": {"claude": "claude-bogus-9"}})
        self.assertEqual(self._main(), ("claude-opus-5-5", "medium"))

    def test_no_opus_in_list_falls_back_to_provider_default(self):
        self.CHOICES = ["claude-haiku-5-5", "claude-sonnet-5-5"]
        self.assertEqual(self._main(model="claude-fable-5-1"), ("claude-sonnet-5-5", "medium"))


if __name__ == "__main__":
    unittest.main()

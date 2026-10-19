"""İşe göre model/effort yönergesi + yeni oturum varsayılanları (TBD#90/#91, stdlib unittest).

Çalıştırma:  python3 py/tests/test_routing_guidance.py -v
`settings.SETTINGS_JSON` geçici dosyaya yönlendirilir, gerçek ayar/AGENTS.md'ye ve docker'a/ağa dokunmaz.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import routing, settings  # noqa: E402
from claudeops.providers import get_provider  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.patches = [
            mock.patch.object(settings, "SETTINGS_JSON", os.path.join(self.dir.name, "settings.json")),
            mock.patch.object(routing, "OVERRIDE_PATH", os.path.join(self.dir.name, "routing-guidance.md")),
            mock.patch.object(routing, "CLAUDEOPS_DIR", self.dir.name),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)


class DefaultsTest(_Tmp):
    def test_claude_defaults_to_newest_sonnet_medium(self):
        p = get_provider("claude")
        with mock.patch.object(type(p), "model_choices", lambda self: ["claude-fable-5-1", "claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5", "claude-sonnet-5-5"]):
            self.assertEqual(settings.default_model_for(p), "claude-sonnet-5-5")
        self.assertEqual(settings.default_effort_for(p), "medium")

    def test_provider_without_model_choices_gives_empty_default(self):
        # Uzak host'ta modeli listelenemeyen CLI: eskiden IndexError ile /api/status 500'lenirdi (yuhem, 2026-10-19).
        p = get_provider("claude")
        with mock.patch.object(type(p), "model_choices", lambda self: []):
            self.assertEqual(settings.default_model_for(p), "")

    def test_override_wins_and_invalid_override_falls_back(self):
        p = get_provider("claude")
        settings.save_settings({"default_effort": {"claude": "high"}})
        self.assertEqual(settings.default_effort_for(p), "high")
        settings.save_settings({"default_effort": {"claude": "bogus"}})
        self.assertEqual(settings.default_effort_for(p), "medium")
        settings.save_settings({"default_effort": {"claude": ""}})
        self.assertNotIn("claude", settings.load_settings()["default_effort"])

    def test_other_providers_keep_old_top_level_effort(self):
        for name in ("agy", "codex", "copilot"):
            p = get_provider(name)
            self.assertEqual(settings.default_effort_for(p), p.effort_levels()[-1], name)


class GuidanceTest(_Tmp):
    def test_enabled_by_default_and_bundled_path_used(self):
        self.assertTrue(settings.routing_guidance_enabled())
        self.assertEqual(routing.claude_guidance_path(), routing.BUNDLED_PATH)
        self.assertTrue(os.path.isfile(routing.BUNDLED_PATH))

    def test_off_disables_flag(self):
        settings.save_settings({"routing_guidance": "off"})
        self.assertIsNone(routing.claude_guidance_path())
        cmd = get_provider("claude").build_inner_command("/x", "claude-sonnet-5-5", "auto", "medium", None, None, "t")
        self.assertNotIn("--append-system-prompt-file", cmd)

    def test_override_text_is_written_and_used(self):
        settings.save_settings({"routing_guidance_text": "ozel yonerge"})
        path = routing.claude_guidance_path()
        self.assertEqual(path, routing.OVERRIDE_PATH)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "ozel yonerge\n")
        cmd = get_provider("claude").build_inner_command("/x", "claude-sonnet-5-5", "auto", "medium", None, None, "t")
        self.assertIn(f"--append-system-prompt-file {path} --model", cmd)

    def test_guidance_failure_never_breaks_spawn(self):
        with mock.patch.object(routing, "routing_text", side_effect=RuntimeError("boom")):
            self.assertIsNone(routing.claude_guidance_path())


class CodexSyncTest(_Tmp):
    def setUp(self):
        super().setUp()
        self.agy = os.path.join(self.dir.name, "GEMINI.md")

    def test_agy_file_is_created_with_only_the_block_and_removed_with_it(self):
        path = self._agents("# Notlar\n")
        self.assertEqual(routing.sync_global_files(path, self.agy)["agy"], "written")
        self.assertTrue(self._read(self.agy).startswith(routing.BLOCK_BEGIN))
        settings.save_settings({"routing_guidance": "off"})
        self.assertEqual(routing.sync_global_files(path, self.agy)["agy"], "removed")
        self.assertFalse(os.path.exists(self.agy))

    def test_existing_agy_file_keeps_user_text(self):
        path = self._agents("x\n")
        with open(self.agy, "w", encoding="utf-8") as f:
            f.write("benim gemini notlarim\n")
        routing.sync_global_files(path, self.agy)
        settings.save_settings({"routing_guidance": "off"})
        routing.sync_global_files(path, self.agy)
        self.assertEqual(self._read(self.agy), "benim gemini notlarim\n")

    def _agents(self, text):
        path = os.path.join(self.dir.name, "AGENTS.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_missing_file_is_not_created(self):
        path = os.path.join(self.dir.name, "yok.md")
        self.assertEqual(routing.sync_global_files(path, os.path.join(self.dir.name, "g.md"))["codex"], "skipped:no file")
        self.assertFalse(os.path.exists(path))

    def test_write_is_idempotent_keeps_rest_and_backs_up(self):
        path = self._agents("# Benim notlarim\n\nmetin\n")
        self.assertEqual(routing.sync_global_files(path, self.agy)["codex"], "written")
        text = self._read(path)
        self.assertTrue(text.startswith("# Benim notlarim\n\nmetin\n"))
        self.assertEqual(text.count(routing.BLOCK_BEGIN), 1)
        self.assertEqual(self._read(path + ".bak-routing"), "# Benim notlarim\n\nmetin\n")
        self.assertEqual(routing.sync_global_files(path, self.agy)["codex"], "unchanged")

    def test_text_change_replaces_block_and_off_removes_it(self):
        path = self._agents("# Notlar\n")
        routing.sync_global_files(path, self.agy)
        settings.save_settings({"routing_guidance_text": "yeni metin"})
        self.assertEqual(routing.sync_global_files(path, self.agy)["codex"], "written")
        text = self._read(path)
        self.assertIn("yeni metin", text)
        self.assertEqual(text.count(routing.BLOCK_BEGIN), 1)
        settings.save_settings({"routing_guidance": "off"})
        self.assertEqual(routing.sync_global_files(path, self.agy)["codex"], "removed")
        self.assertEqual(self._read(path), "# Notlar\n")


if __name__ == "__main__":
    unittest.main()

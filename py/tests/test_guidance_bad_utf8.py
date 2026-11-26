"""TBD#373 (3): bozuk UTF-8 yönerge dosyası spawn'ı / eşitlemeyi düşürmez, dosya ezilmez; claude'da diag kaydı kalır."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import routing, settings  # noqa: E402
from claudeops.providers import get_provider  # noqa: E402

BAD = b"kullanici notu\n\xff\xfe\n"


class BadUtf8Test(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        for p in (mock.patch.object(settings, "SETTINGS_JSON", os.path.join(d.name, "settings.json")),
                  mock.patch.object(routing, "OVERRIDE_PATH", os.path.join(d.name, "routing-guidance.md")),
                  mock.patch.object(routing, "CLAUDEOPS_DIR", d.name)):
            p.start()
            self.addCleanup(p.stop)
        settings.save_settings({"routing_guidance_text": "ozel yonerge"})

    def _file(self, name):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(BAD)
        return path

    def _read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_claude_override_unreadable_is_logged_and_left_untouched(self):
        path = self._file("routing-guidance.md")
        with mock.patch.object(routing, "diag_log", create=True) as log:
            self.assertIsNone(routing.claude_guidance_path())
            cmd = get_provider("claude").build_inner_command("/x", "claude-sonnet-5-5", "auto", "medium", None, None, "t")
        self.assertNotIn("--append-system-prompt-file", cmd)
        self.assertEqual(self._read(path), BAD)
        self.assertEqual(log.call_args.args, ("routing_guidance_unreadable",))
        self.assertEqual(log.call_args.kwargs, {"path": path, "error": "UnicodeDecodeError"})

    def test_sync_skips_bad_file_and_still_syncs_the_other(self):
        codex = self._file("AGENTS.md")
        agy = os.path.join(self.dir, "GEMINI.md")
        with mock.patch.object(routing, "diag_log", create=True) as log:
            res = routing.sync_global_files(codex_path=codex, agy_path=agy)
        self.assertEqual(res, {"codex": "skipped:UnicodeDecodeError", "agy": "written"})
        self.assertEqual(self._read(codex), BAD)
        self.assertFalse(os.path.exists(codex + ".bak-routing"))
        self.assertEqual(log.call_args.kwargs, {"path": codex, "error": "UnicodeDecodeError"})

    def test_sync_bad_agy_file_is_not_removed(self):
        agy = self._file("GEMINI.md")
        settings.save_settings({"routing_guidance": "off"})
        res = routing.sync_global_files(codex_path=os.path.join(self.dir, "yok.md"), agy_path=agy)
        self.assertEqual(res["agy"], "skipped:UnicodeDecodeError")
        self.assertEqual(self._read(agy), BAD)


if __name__ == "__main__":
    unittest.main()

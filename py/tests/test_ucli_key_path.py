"""ucli anahtar dosya yolu TEK yardımcıda (paths.ucli_key_file); çağıranlar ondan türetir."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import paths  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402


class UcliKeyPathTest(unittest.TestCase):
    def test_default_and_service(self):
        base = os.path.expanduser("~/.claude/claudeops")
        self.assertEqual(paths.ucli_key_file(), os.path.join(base, "ucli_api_key"))
        self.assertEqual(paths.ucli_key_file("groq"), os.path.join(base, "ucli_key_groq"))

    def test_callers_share_helper(self):
        self.assertEqual(up._API_KEY_FILE, paths.ucli_key_file())
        self.assertEqual(wr.UCLI_KEY_FILE, paths.ucli_key_file())
        with mock.patch.object(paths, "CLAUDEOPS_DIR", os.path.expanduser("~/.claude/claudeops")):    # varsayılan örnek
            self.assertEqual(up._service_key_file("openrouter"), paths.ucli_key_file("openrouter"))


class RemovedServiceKeyTest(unittest.TestCase):
    """TBD#451 (a): anahtar ayardan kaldırılınca açılış reddedilir VE bu örneğin yazdığı hizmet anahtarı dosyası silinir."""

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.d, True)
        self.key = os.path.join(self.d, "ucli_key_grok")
        for p in (mock.patch.object(up, "_service_key_file", lambda s: os.path.join(self.d, f"ucli_key_{s}")),
                  mock.patch.object(up, "_services", lambda: {"grok": ("", "https://x/v1", "XAI_API_KEY")}),
                  mock.patch.object(up, "byok_env_for", lambda cli: {})):
            p.start()
            self.addCleanup(p.stop)

    def refuse(self):
        with self.assertRaisesRegex(ValueError, "anahtar yok"):
            up._apply_cli_opts(["/bin/ucli"], {"service": "grok"}, session_name="s1")

    def test_stale_key_file_is_removed(self):
        with open(self.key, "w") as f:
            f.write("eski")
        self.refuse()
        self.assertFalse(os.path.lexists(self.key))

    def test_symlink_itself_is_removed_target_kept(self):
        target = os.path.join(self.d, "hedef")
        with open(target, "w") as f:
            f.write("h")
        os.symlink(target, self.key)
        self.refuse()
        self.assertFalse(os.path.lexists(self.key))
        self.assertTrue(os.path.exists(target))

    def test_missing_file_still_refuses(self):
        self.refuse()

    def test_dry_run_keeps_the_file(self):
        from claudeops import preview
        with open(self.key, "w") as f:
            f.write("eski")
        with mock.patch.object(preview, "active", lambda: True):
            self.refuse()
        self.assertTrue(os.path.exists(self.key))


if __name__ == "__main__":
    unittest.main()

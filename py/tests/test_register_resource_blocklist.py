"""http_register `resources`: gizli dosyalar proje kaynaklar/ altına kopyalanmaz."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class ResourceBlocklistTest(unittest.TestCase):
    def test_blocks_secret_dirs_and_names(self):
        home = os.path.expanduser("~")
        for p in (f"{home}/.ssh/id_ed25519", f"{home}/.claude/claudeops/web.token", f"{home}/.aws/credentials",
                  "/tmp/x/.env", "/tmp/x/server.pem", "/tmp/x/my_api_key.txt"):
            self.assertTrue(ws._resource_blocked(p), p)

    def test_allows_ordinary_files(self):
        for p in ("/tmp/x/paper.pdf", os.path.expanduser("~/work/notes.md")):
            self.assertFalse(ws._resource_blocked(p), p)

    def test_symlink_into_secret_dir_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "plain.txt")
            open(target, "w").close()
            link = os.path.join(d, "innocent.pdf")
            os.symlink(os.path.expanduser("~/.ssh"), link)   # dizine symlink: realpath ~/.ssh altında
            self.assertTrue(ws._resource_blocked(link))
            self.assertFalse(ws._resource_blocked(target))


if __name__ == "__main__":
    unittest.main()

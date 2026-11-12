"""review R-4 (web_orch): `_write_private` atomik, symlink izlemez, 0600."""
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_orch  # noqa: E402


class WritePrivateTest(unittest.TestCase):
    def test_mode_overwrite_and_no_tmp_left(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "f.md")
        web_orch._write_private(p, "bir")
        os.chmod(p, 0o666)
        web_orch._write_private(p, "iki")
        self.assertEqual(open(p, encoding="utf-8").read(), "iki")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual(os.listdir(d), ["f.md"])

    def test_symlink_target_not_followed(self):
        d = tempfile.mkdtemp()
        victim = os.path.join(d, "victim.txt")
        open(victim, "w").write("dokunma")
        p = os.path.join(d, "f.md")
        os.symlink(victim, p)
        web_orch._write_private(p, "yeni")
        self.assertEqual(open(victim).read(), "dokunma")
        self.assertFalse(os.path.islink(p))
        self.assertEqual(open(p, encoding="utf-8").read(), "yeni")


if __name__ == "__main__":
    unittest.main()

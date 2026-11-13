"""files.rename_path: hedef sonradan belirirse EZMEZ (link() atomik); symlink adı değişir, hedefi dokunulmaz (P3 #42)."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import files  # noqa: E402


class RenameNoClobberTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.s = NS(cwd=self.root, cli="shell")

    def p(self, n):
        return os.path.join(self.root, n)

    def test_plain_rename(self):
        open(self.p("a"), "w").write("A")
        r = files.rename_path(self.s, self.p("a"), "b")
        self.assertTrue(r["ok"], r)
        self.assertFalse(os.path.lexists(self.p("a")))
        self.assertEqual(open(self.p("b")).read(), "A")

    def test_target_appearing_after_check_is_not_overwritten(self):
        open(self.p("a"), "w").write("A")
        real_lexists = os.path.lexists
        calls = {"n": 0}

        def racy(path):
            res = real_lexists(path)
            if path == self.p("b") and calls["n"] == 0:      # denetim geçtikten SONRA hedef beliriyor
                calls["n"] += 1
                open(self.p("b"), "w").write("OTHER")
            return res
        with mock.patch.object(files.os.path, "lexists", racy):
            r = files.rename_path(self.s, self.p("a"), "b")
        self.assertEqual((r["ok"], r.get("error")), (False, "exists"))
        self.assertEqual(open(self.p("b")).read(), "OTHER")
        self.assertEqual(open(self.p("a")).read(), "A")

    def test_rename_falls_back_when_hardlink_forbidden(self):
        """review R-2: link() EPERM/EXDEV verirse (hard-link'siz FS) rename yoluna düş."""
        import errno
        open(self.p("a"), "w").write("A")
        def nolink(*a, **k):
            raise OSError(errno.EPERM, "no hard links")
        with mock.patch.object(files.os, "link", nolink):
            r = files.rename_path(self.s, self.p("a"), "b")
        self.assertTrue(r["ok"], r)
        self.assertEqual(open(self.p("b")).read(), "A")
        self.assertFalse(os.path.lexists(self.p("a")))

    def test_symlink_renamed_not_followed(self):
        open(self.p("t"), "w").write("T")
        os.symlink(self.p("t"), self.p("l"))
        self.assertTrue(files.rename_path(self.s, self.p("l"), "l2")["ok"])
        self.assertTrue(os.path.islink(self.p("l2")))
        self.assertEqual(open(self.p("t")).read(), "T")

    def test_directory_rename(self):
        os.mkdir(self.p("d"))
        self.assertTrue(files.rename_path(self.s, self.p("d"), "e")["ok"])
        self.assertTrue(os.path.isdir(self.p("e")))


if __name__ == "__main__":
    unittest.main()

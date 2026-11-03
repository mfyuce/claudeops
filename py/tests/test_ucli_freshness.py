"""GATE-TODO4 madde 3: bin/ucli.info source_git ile unified-cli HEAD karsilastirmasi (sahte git, ag/surec yok)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_freshness as uf  # noqa: E402


class TestFreshness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = os.path.join(self.tmp.name, "ucli")
        self.src = os.path.join(self.tmp.name, "src")
        os.makedirs(self.src)

    def _info(self, text):
        with open(self.bin + ".info", "w", encoding="utf-8") as f:
            f.write(text)

    def _git(self, head, count):
        def g(src, *a):
            if a[:2] == ("rev-parse", "--short"):
                return head
            if a[0] == "rev-list":
                self.assertEqual(a[2], "abc1234..HEAD")
                return count
            return None
        return g

    def test_behind_is_stale_with_count_in_message(self):
        self._info("source_git=abc1234\nprofile=release\n")
        r = uf.freshness(self.bin, self.src, self._git("def5678", "3"))
        self.assertTrue(r["stale"])
        self.assertEqual(r["behind"], 3)
        self.assertIn("3 commit geride", r["message"])
        self.assertIn("install-ucli.sh", r["message"])

    def test_same_head_is_fresh(self):
        self._info("source_git=abc1234\n")
        r = uf.freshness(self.bin, self.src, self._git("abc1234", "0"))
        self.assertFalse(r["stale"])
        self.assertEqual(r["message"], "")

    def test_missing_or_dash_info_is_not_stale_but_explains(self):
        r = uf.freshness(self.bin, self.src, self._git("x", "1"))
        self.assertFalse(r["stale"])
        self.assertIn("ucli.info", r["message"])
        self._info("source_git=-\n")
        self.assertFalse(uf.freshness(self.bin, self.src, self._git("x", "1"))["stale"])

    def test_git_failure_never_raises_or_alarms(self):
        self._info("source_git=abc1234\n")
        r = uf.freshness(self.bin, self.src, lambda *a: None)
        self.assertFalse(r["stale"])

    def test_missing_source_dir_is_silent(self):
        self._info("source_git=abc1234\n")
        r = uf.freshness(self.bin, os.path.join(self.tmp.name, "yok"), self._git("d", "2"))
        self.assertFalse(r["stale"])


if __name__ == "__main__":
    unittest.main()

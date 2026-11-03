"""GATE-TODO4 madde 4: RTODO/RTBD exclude denetimi, gecici git depolariyla; hicbir sey yazilmaz.
Calistirma: python3 -m unittest discover -s py/tests"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import exclude_check as ec  # noqa: E402

HAVE_GIT = shutil.which("git") is not None


def _git(cwd, *a):
    subprocess.run(["git", "-C", cwd, "-c", "user.email=t@t", "-c", "user.name=t", *a],
                   check=True, capture_output=True)


@unittest.skipUnless(HAVE_GIT, "git yok")
class TestExcludeCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def repo(self, name, exclude=""):
        d = os.path.join(self.tmp.name, name)
        os.makedirs(d)
        _git(d, "init", "-q")
        if exclude:
            with open(os.path.join(d, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
                f.write(exclude)
        return d

    def test_ok_when_both_excluded(self):
        d = self.repo("a", "RTODO.md\nRTBD.md\n")
        self.assertEqual(ec.check_repo("a", d)["state"], "ok")

    def test_missing_exclude_is_reported_with_names(self):
        d = self.repo("b", "RTODO.md\n")
        r = ec.check_repo("b", d)
        self.assertEqual(r["state"], "missing_exclude")
        self.assertEqual(r["not_excluded"], ["RTBD.md"])

    def test_comment_and_negation_do_not_count(self):
        d = self.repo("c", "# RTODO.md\n!RTBD.md\n")
        self.assertEqual(ec.check_repo("c", d)["not_excluded"], ["RTODO.md", "RTBD.md"])

    def test_tracked_file_is_a_trace(self):
        d = self.repo("t", "RTODO.md\nRTBD.md\n")
        with open(os.path.join(d, "RTODO.md"), "w") as f:
            f.write("x\n")
        _git(d, "add", "-f", "RTODO.md")
        r = ec.check_repo("t", d)
        self.assertEqual(r["state"], "tracked")
        self.assertEqual(r["tracked"], ["RTODO.md"])

    def test_non_git_and_missing_dir_are_skipped_not_errors(self):
        plain = os.path.join(self.tmp.name, "plain")
        os.makedirs(plain)
        self.assertEqual(ec.check_repo("p", plain)["state"], "not_git")
        self.assertEqual(ec.check_repo("q", os.path.join(self.tmp.name, "yok"))["state"], "no_dir")
        self.assertEqual(ec.check_repo("r", "")["state"], "no_dir")

    def test_check_never_writes_and_report_lists_only_problems(self):
        d = self.repo("w", "RTODO.md\n")
        ex = os.path.join(d, ".git", "info", "exclude")
        before = open(ex, encoding="utf-8").read()
        rows = ec.check_all({"w": d, "ok": self.repo("ok", "RTODO.md\nRTBD.md\n")})
        self.assertEqual(open(ex, encoding="utf-8").read(), before)
        self.assertEqual([r["project"] for r in ec.problems(rows)], ["w"])
        rep = ec.format_report(rows)
        self.assertIn("w:", rep)
        self.assertFalse([ln for ln in rep.splitlines() if ln.startswith("ok:")])

    def test_clean_report_message(self):
        rows = ec.check_all({"ok": self.repo("ok2", "RTODO.md\nRTBD.md\n")})
        self.assertIn("iz yok", ec.format_report(rows))


if __name__ == "__main__":
    unittest.main()

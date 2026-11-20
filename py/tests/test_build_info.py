import os, subprocess, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import build_info as bi  # noqa: E402


def _git(d, *a):
    subprocess.run(["git", "-C", d, "-c", "user.email=a@b", "-c", "user.name=t", *a], check=True, capture_output=True)


class T(unittest.TestCase):
    def test_stale_when_disk_moves_ahead_of_running(self):
        d = tempfile.mkdtemp()
        _git(d, "init", "-q"); _git(d, "commit", "-q", "--allow-empty", "-m", "a")
        first = bi._head(d)
        with mock.patch.object(bi, "RUNNING", first):
            self.assertFalse(bi.info(d)["stale"])
            _git(d, "commit", "-q", "--allow-empty", "-m", "b")
            i = bi.info(d)
        self.assertTrue(i["stale"])
        self.assertEqual((i["running"], i["disk"] != first), (first, True))

    def test_no_git_is_empty_not_stale(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(bi, "RUNNING", ""):
            self.assertEqual((bi.info(d)["disk"], bi.info(d)["stale"]), ("", False))


if __name__ == "__main__":
    unittest.main()

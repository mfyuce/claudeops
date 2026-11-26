"""TBD#375 (b) 7: `changed_after_review` bulgu yolunu git'e harfi harfine verir (`[a].py` kalıp sayılmaz).
Geçici git deposu; ağ yok. Çalıştırma: python3 -m unittest discover -s py/tests"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402


class TestChangedAfterReviewLiteralPath(unittest.TestCase):
    def test_glob_like_name_is_not_matched_as_pattern(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = os.path.join(tmp.name, "g")
        os.makedirs(repo)

        def git(*args, when=None):
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
            if when is not None:
                env.update(GIT_AUTHOR_DATE=f"@{when} +0000", GIT_COMMITTER_DATE=f"@{when} +0000")
            subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                           capture_output=True, env=env, timeout=30)

        for name in ("a.py", "[a].py"):
            with open(os.path.join(repo, name), "w") as fh:
                fh.write("x")
            os.utime(os.path.join(repo, name), (1000, 1000))
        git("init", "-q")
        git("add", "--", "a.py")
        git("commit", "-qm", "sonra", when=2_000_000_000)          # yalnız a.py rapordan SONRA commit'li
        report = os.path.join(tmp.name, "r.md")
        with open(report, "w") as fh:
            fh.write("r")
        os.utime(report, (1_900_000_000, 1_900_000_000))
        row = lambda n: {"where": n + ":1", "review_file": report}     # noqa: E731
        self.assertTrue(rv.changed_after_review(row("a.py"), repo))
        self.assertFalse(rv.changed_after_review(row("[a].py"), repo))


if __name__ == "__main__":
    unittest.main()

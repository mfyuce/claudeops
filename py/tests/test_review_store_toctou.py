"""commit_reviews TOCTOU: taramadan sonra gizli değer eklenen dosya commit'e girmez."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review_store as rs  # noqa: E402

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


class ToctouTest(unittest.TestCase):
    def test_file_changed_after_scan_with_secret_is_held(self):
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "main")
            os.makedirs(os.path.join(root, "reviews"))
            gd = os.path.join(d, "prv.git")
            subprocess.run(["git", "init", "-q", "--bare", gd], check=True, env=ENV)
            f = os.path.join(root, "reviews", "a.md")
            with open(f, "w") as fh:
                fh.write("temiz")
            calls = {"n": 0}

            def scan(txt):
                calls["n"] += 1
                if calls["n"] == 1:                  # ilk tarama geçti; sonra dosya değişir
                    with open(f, "w") as fh:
                        fh.write("SECRET")
                    return txt
                return txt.replace("SECRET", "***")

            res = rs.commit_reviews(root, gd, scan, dry=False)
            self.assertEqual(res["committed"], 0)
            self.assertIn("reviews/a.md", res["held"])


if __name__ == "__main__":
    unittest.main()

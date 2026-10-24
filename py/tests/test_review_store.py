"""TBD#118 devam: görünürlük/hedef koruması + -prv günlük commit. Gerçek ağ/gh/glab YOK; yalnız geçici yerel git depoları."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review_store as rs  # noqa: E402

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, env=ENV).stdout


def scan(txt):
    from claudeops import review as rv
    return rv.redact_secrets(txt)


class PureTest(unittest.TestCase):
    def test_parse_remote(self):
        self.assertEqual(rs.parse_remote("git@github.com:mfyuce/claudeops.git"), ("github.com", "mfyuce/claudeops"))
        self.assertEqual(rs.parse_remote("https://gitlab.com/a/b/c"), ("gitlab.com", "a/b/c"))
        self.assertEqual(rs.parse_remote("/srv/local.git"), ("", ""))

    def test_dest_guard(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(rs.dest_guard(os.path.join(d, "plain", "reviews")), (True, ""))   # git deposu değil
            git("init", "-q", d)
            ok, why = rs.dest_guard(os.path.join(d, "reviews"))                                # izlenebilir + remote yok = unknown
            self.assertFalse(ok)
            self.assertIn("public repoya", why)
            with open(os.path.join(d, ".gitignore"), "w") as f:
                f.write("/reviews/\n")
            self.assertEqual(rs.dest_guard(os.path.join(d, "reviews")), (True, ""))            # yok sayılıyor: girmez

    def test_visibility_any_public_wins_and_cache(self):
        calls = []

        class R:
            def __init__(self, rc, out):
                self.returncode, self.stdout, self.stderr = rc, out, ""

        def run(argv, **kw):
            calls.append(argv[0])
            if argv[0] == "git":
                return R(0, "o\tgit@github.com:a/b.git (fetch)\nl\tgit@gitlab.com:a/b.git (fetch)\n")
            if argv[0] == "gh":
                return R(0, "true")
            return R(0, '{"visibility": "public"}')
        rs._CACHE.clear()
        self.assertEqual(rs.repo_visibility("/x", run=run, now=1.0), "public")
        n = len(calls)
        self.assertEqual(rs.repo_visibility("/x", run=run, now=2.0), "public")
        self.assertEqual(len(calls), n)                                                        # önbellekten


class CommitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.main = os.path.join(d, "main")
        git("init", "-q", self.main)
        with open(os.path.join(self.main, ".gitignore"), "w") as f:
            f.write("/reviews/\n")
        with open(os.path.join(self.main, "a.txt"), "w") as f:
            f.write("a\n")
        git("-C", self.main, "add", "a.txt", ".gitignore")
        git("-C", self.main, "commit", "-q", "-m", "init")
        self.gd = os.path.join(d, "prv.git")
        git("init", "-q", "--bare", self.gd)
        self.remotes = []
        for n in ("origin", "gitlab"):
            r = os.path.join(d, n + ".git")
            git("init", "-q", "--bare", r)
            git("--git-dir=" + self.gd, "remote", "add", n, r)
            self.remotes.append(r)
        self.rdir = os.path.join(self.main, "reviews", "p", "evren", "m", "20261024100000")
        os.makedirs(self.rdir)
        self.write("20261024100000.md", "## R-1 | P1 | a | t\n")
        self.write("20261024100000.usage.jsonl", "{}\n")
        self.write("20261024100001.md", "DSN postgres://u:hunter2pw@h/db\n")

    def write(self, name, txt):
        with open(os.path.join(self.rdir, name), "w") as f:
            f.write(txt)

    def test_dry_run_lists_without_touching_anything(self):
        r = rs.commit_reviews(self.main, self.gd, scan, dry=True)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["would"]), 2)
        self.assertEqual([h.split("/")[-1] for h in r["held"]], ["20261024100001.md"])        # gizli değer dışarıda
        self.assertEqual(git("-C", self.remotes[0], "branch", "-a").strip(), "")               # hiçbir şey itilmedi

    def test_act_commits_only_reviews_to_prv_and_pushes_both(self):
        main_head = git("-C", self.main, "rev-parse", "HEAD").strip()
        with open(os.path.join(self.main, "a.txt"), "a") as f:
            f.write("kirli ana dosya\n")                                                       # eklenmemeli
        r = rs.commit_reviews(self.main, self.gd, scan, dry=False)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["committed"], sorted(r["pushed"])), (2, ["gitlab", "origin"]))
        files = git("--git-dir=" + self.gd, "ls-tree", "-r", "--name-only", "HEAD").split()
        self.assertTrue(files and all(f.startswith("reviews/") for f in files), files)
        self.assertFalse(any(f.endswith("20261024100001.md") for f in files))
        self.assertEqual(git("-C", self.main, "rev-parse", "HEAD").strip(), main_head)         # ana repoya hiçbir şey girmedi
        self.assertEqual(git("-C", self.main, "log", "--oneline").count("\n"), 1)
        for rem in self.remotes:
            self.assertIn("reviews/", git("--git-dir=" + rem, "ls-tree", "-r", "--name-only", "HEAD"))
        again = rs.commit_reviews(self.main, self.gd, scan, dry=False)                         # ikinci tur: yeni dosya yok
        self.assertEqual((again["would"], again["committed"]), ([], 0))

    def test_act_works_from_foreign_cwd(self):
        # servis cwd'si py/: git yolları kök'e göre çözülmeli (canlıda "pathspec did not match" idi)
        sub = os.path.join(self.main, "sub")
        os.makedirs(sub)
        old = os.getcwd()
        os.chdir(sub)
        try:
            r = rs.commit_reviews(self.main, self.gd, scan, dry=False)
        finally:
            os.chdir(old)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["committed"], 2)

    def test_refuses_main_repo_git_dir(self):
        r = rs.commit_reviews(self.main, os.path.join(self.main, ".git"), scan, dry=False)
        self.assertFalse(r["ok"])
        self.assertEqual(git("-C", self.main, "log", "--oneline").count("\n"), 1)


class StoreCommitGateTest(CommitTest):
    """`web_review.store_commit`: ayar kapalıyken dokunmaz; ilk gün KURU, sonraki günlük tur act; günde bir."""
    def cfg(self, on=True):
        from types import SimpleNamespace as NS
        return NS(sid="rev", review_store_dir=self.main, review_store_commit=on, review_store_git_dir=self.gd)

    def test_off_dry_first_then_act_daily(self):
        from unittest import mock
        from claudeops import steward as sw
        from claudeops.commands import web_review as wr
        root = os.path.join(self.tmp.name, "stew")
        os.makedirs(root)
        asked = []
        with mock.patch.object(sw, "paths_for", lambda sid: type("P", (), {"root": root})()), \
                mock.patch.object(sw, "log_event", lambda *a, **k: None), \
                mock.patch.object(sw, "add_question", lambda *a, **k: asked.append(a) or type("Q", (), {})()), \
                mock.patch.object(wr, "_NOTIFY_FN", None):
            self.assertEqual(wr.store_commit(self.cfg(False), 1000.0), 0)
            self.assertFalse(os.path.exists(os.path.join(root, "review_store_commit.json")))
            self.assertEqual(wr.store_commit(self.cfg(), 1000.0), 0)                          # ilk tur kuru
            self.assertEqual(git("--git-dir=" + self.gd, "rev-list", "--all", "--count").strip(), "0")
            self.assertEqual(len(asked), 1)                                                   # tutulan dosya için sahibe soru
            self.assertEqual(wr.store_commit(self.cfg(), 1000.0 + 3600), 0)                   # günde bir
            self.assertEqual(wr.store_commit(self.cfg(), 1000.0 + 25 * 3600), 2)              # ikinci gün act
            self.assertEqual(git("--git-dir=" + self.gd, "rev-list", "--all", "--count").strip(), "1")


if __name__ == "__main__":
    unittest.main()

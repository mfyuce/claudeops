"""TBD#118 devam: görünürlük/hedef koruması + -prv günlük commit. Gerçek ağ/gh/glab YOK; yalnız geçici yerel git depoları."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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

    def test_dest_guard_fails_closed_on_check_ignore_error(self):
        from types import SimpleNamespace as NS

        def run(argv, **kw):
            if "rev-parse" in argv:
                return NS(returncode=0, stdout="/repo\n", stderr="")
            return NS(returncode=128, stdout="", stderr="fatal: boom")   # check-ignore hata
        ok, why = rs.dest_guard("/nonexistent/reviews", run=run)
        self.assertFalse(ok)
        self.assertIn("check-ignore", why)

    def test_dest_guard_localized_not_a_repo_is_rejected_not_open(self):
        from types import SimpleNamespace as NS
        run = lambda argv, **kw: NS(returncode=128, stdout="", stderr="fatal: kein Git-Repository")
        self.assertFalse(rs.dest_guard("/nonexistent/reviews", run=run)[0])

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
        # Test edilen kod `git commit`i os.environ ile çalıştırır: genel git kimliğine (gerçek HOME) bağımlı OLMASIN (D13)
        env = mock.patch.dict(os.environ, {k: ENV[k] for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")})
        env.start()
        self.addCleanup(env.stop)
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

    def test_glob_chars_in_filename_are_literal(self):
        self.write("rapor[1]*.md", "## R-1 | P1 | a | t\n")
        self.write("rapor1x.md", "## R-2 | P1 | a | t\n")
        r = rs.commit_reviews(self.main, self.gd, scan, dry=False)
        self.assertTrue(r["ok"], r)
        files = git("--git-dir=" + self.gd, "ls-tree", "-r", "--name-only", "HEAD").split("\n")
        self.assertTrue(any(f.endswith("rapor[1]*.md") for f in files), files)
        self.assertTrue(any(f.endswith("rapor1x.md") for f in files), files)

    def test_junk_files_skipped(self):
        for n in (".x.upload.tmp", "a.md.tmp", "b.lock", "c.md~", ".d.swp"):
            self.write(n, "yarım\n")
        r = rs.commit_reviews(self.main, self.gd, scan, dry=True)
        self.assertEqual(len(r["would"]), 2)

    def test_secret_written_between_scan_and_add_is_unstaged(self):
        """Tarama ile `git add` arası içerik değişirse (TOCTOU) index'e giren blob taranır, gizli değer commit'lenmez."""
        real_git = rs._git

        def racing(base, *args, **kw):
            if args and args[0] == "add":
                self.write("20261024100000.md", "DSN postgres://u:hunter2pw@h/db\n")
            return real_git(base, *args, **kw)
        with mock.patch.object(rs, "_git", racing):
            r = rs.commit_reviews(self.main, self.gd, scan, dry=False)
        files = git("--git-dir=" + self.gd, "ls-tree", "-r", "--name-only", "HEAD").split()
        self.assertFalse(any(f.endswith("20261024100000.md") for f in files), files)
        self.assertTrue(any(h.endswith("20261024100000.md") for h in r["held"]), r)

    def test_saved_page_files_dirs_are_skipped(self):
        side = os.path.join(self.main, "reviews", "p", "agy", "Sayfa_files")
        os.makedirs(side)
        with open(os.path.join(side, "lazy.min.js"), "w") as f:
            f.write("var x=1;\n")
        r = rs.commit_reviews(self.main, self.gd, scan, dry=True)
        self.assertEqual(len(r["would"]), 2)
        self.assertFalse(any("_files" in w for w in r["would"] + r["held"]))

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

    def test_unpushed_local_commit_is_pushed_on_next_run(self):
        # 1. tur: remote'lar geçici bozuk -> commit olur, push başarısız
        bad = {}
        for n in ("origin", "gitlab"):
            bad[n] = self.remotes[0 if n == "origin" else 1]
            git("--git-dir=" + self.gd, "remote", "set-url", n, os.path.join(self.tmp.name, "yok-" + n + ".git"))
        r1 = rs.commit_reviews(self.main, self.gd, scan, dry=False)
        self.assertFalse(r1["ok"])
        self.assertEqual(r1["committed"], 2)
        # 2. tur: remote'lar düzelir, yeni dosya YOK -> yine de push edilmeli
        for n, path in bad.items():
            git("--git-dir=" + self.gd, "remote", "set-url", n, path)
        r2 = rs.commit_reviews(self.main, self.gd, scan, dry=False)
        self.assertEqual((r2["would"], r2["committed"]), ([], 0))
        self.assertTrue(r2["ok"], r2)
        self.assertEqual(sorted(r2["pushed"]), ["gitlab", "origin"])
        for rem in self.remotes:
            self.assertIn("reviews/", git("--git-dir=" + rem, "ls-tree", "-r", "--name-only", "HEAD"))

    def test_no_commit_yet_and_nothing_new_is_noop(self):
        for f in os.listdir(self.rdir):
            os.remove(os.path.join(self.rdir, f))
        r = rs.commit_reviews(self.main, self.gd, scan, dry=False)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["committed"], r["pushed"]), (0, []))

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


class ParseRemotePortTest(unittest.TestCase):
    def test_ssh_port_and_alt_hosts(self):
        from claudeops import review_store as rs
        self.assertEqual(rs.parse_remote("ssh://git@github.com:22/o/r.git"), ("github.com", "o/r"))
        self.assertEqual(rs.parse_remote("ssh://git@ssh.github.com:443/o/r.git"), ("github.com", "o/r"))
        self.assertEqual(rs.parse_remote("ssh://git@altssh.gitlab.com:443/o/r"), ("gitlab.com", "o/r"))
        self.assertEqual(rs.parse_remote("git@github.com:123/r.git"), ("github.com", "123/r"))     # scp biçimi: sayısal sahip port DEĞİL
        self.assertEqual(rs.parse_remote("git@github.com:o/r.git"), ("github.com", "o/r"))

    def test_unknown_not_cached(self):
        from claudeops import review_store as rs
        rs._CACHE.clear()
        calls = []

        def run(argv, **k):
            calls.append(argv)
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        rs.repo_visibility("/nonexistent-x", run=run)
        n1 = len(calls)
        rs.repo_visibility("/nonexistent-x", run=run)
        self.assertGreater(len(calls), n1)       # unknown önbelleğe alınmadı: ikinci çağrı yeniden çalıştı

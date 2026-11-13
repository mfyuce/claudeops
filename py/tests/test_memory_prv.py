"""memory-backup -prv kipi: hafıza ana repoya girmez, kişisel <ad>-prv'ye (yeni gitdir + iki remote) gider. Gerçek git, sahte gh/glab + yerel bare remote'lar."""
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from claudeops.commands import memory_backup as mb


def git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


class Env(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.home = os.path.join(self.t, "home")
        self.remotes = os.path.join(self.t, "remotes")
        os.makedirs(self.remotes)
        self.proj_root = os.path.join(self.home, ".claude", "projects")
        self.created = []
        self.existing = set()
        p = mock.patch.object(mb, "_run", self.fake_run)
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(mb, "CREATED_LOG", os.path.join(self.t, "created.log"))
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(mb.os.path, "expanduser", lambda x: x.replace("~", self.home))
        p.start(); self.addCleanup(p.stop)

    def bare(self, kind, name):
        d = os.path.join(self.remotes, kind, name + ".git")
        if not os.path.isdir(d):
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", d], check=True)
        return d

    def fake_run(self, argv, cwd=None, timeout=60):
        if argv[0] == "gh" and argv[1:3] == ["repo", "view"]:
            return (0, "{}") if argv[3] in self.existing else (1, "")
        if argv[0] == "glab" and argv[1:3] == ["repo", "view"]:
            return (0, "{}") if argv[3] in self.existing else (1, "")
        if argv[0] in ("gh", "glab") and argv[1] == "api":
            return 0, "mfyuce"
        if argv[0] in ("gh", "glab") and argv[1:3] == ["repo", "create"]:
            kind = "github" if argv[0] == "gh" else "gitlab"
            name = argv[3].split("/")[-1]
            self.bare(kind, name)
            self.created.append((kind, name, "--private" in argv))
            return 0, ""
        argv = [a.replace("git@github.com:mfyuce/", "file://" + os.path.join(self.remotes, "github") + "/")
                 .replace("git@gitlab.com:mfyuce/", "file://" + os.path.join(self.remotes, "gitlab") + "/") for a in argv]
        try:
            p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                               env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
            return p.returncode, p.stdout or ""
        except (OSError, subprocess.SubprocessError):
            return 127, ""

    def project(self, name, files=None, remote=None, tracked_memory=False):
        cwd = os.path.join(self.t, "work", name)
        os.makedirs(cwd)
        git("init", "-q", "-b", "main", cwd=cwd)
        if remote:
            git("remote", "add", "origin", remote, cwd=cwd)
        if tracked_memory:
            os.makedirs(os.path.join(cwd, "memory"))
            open(os.path.join(cwd, "memory", "old.md"), "w").write("old")
            git("add", "memory/old.md", cwd=cwd)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "old"], cwd=cwd, check=True)
        enc = cwd.replace("/", "-")
        pd = os.path.join(self.proj_root, enc)
        os.makedirs(os.path.join(pd, "memory"))
        for f, text in (files or {"a.md": "fact a"}).items():
            open(os.path.join(pd, "memory", f), "w").write(text)
        open(os.path.join(pd, "s.jsonl"), "w").write(json.dumps({"cwd": cwd}) + "\n")
        return cwd, name

    def roster(self, *cwds):
        return {os.path.realpath(c): os.path.basename(c) for c in cwds}

    def marks(self, *cwds):
        return {os.path.basename(c): "on" for c in cwds}


class Plan(Env):
    def test_new_project_plans_creation_exclude_and_files(self):
        cwd, _ = self.project("alpha")
        ents, _ = mb.run_prv(self.proj_root, False, [], self.roster(cwd), self.marks(cwd))
        e = ents[0]
        self.assertEqual(e["status"], "ok")
        self.assertEqual(e["prv_state"], "yeni")
        self.assertIn("exclude /memory/", e["actions"])
        self.assertEqual([(k, n, ex) for k, n, ex in e["creates"]], [("github", "alpha-prv", False), ("gitlab", "alpha-prv", False)])
        self.assertEqual(self.created, [])                         # dry-run: hiçbir şey oluşturulmaz
        self.assertFalse(os.path.exists(mb.gitdir_of("alpha")))
        self.assertFalse(os.path.exists(os.path.join(cwd, "memory")))

    def test_not_in_roster_skipped(self):
        cwd, _ = self.project("beta")
        ents, _ = mb.run_prv(self.proj_root, False, [], {}, {})
        self.assertEqual(ents[0]["reason"], "roster dışı")

    def test_secret_skips_and_reports(self):
        cwd, _ = self.project("gamma", {"x.md": "password=hunter2xx"})
        ents, _ = mb.run_prv(self.proj_root, False, [], self.roster(cwd), self.marks(cwd))
        self.assertIn("sır taraması", ents[0]["reason"])

    def test_company_remote_marked_never_pushed_to(self):
        cwd, _ = self.project("corp", remote="git@git.corp.example:team/corp.git")
        ents, _ = mb.run_prv(self.proj_root, False, [], self.roster(cwd), self.marks(cwd))
        self.assertTrue(ents[0]["company"])
        self.assertEqual(ents[0]["status"], "ok")

    def test_name_collision_second_skipped(self):
        a, _ = self.project("dup")
        # ikinci repo aynı ada (farklı üst dizin)
        cwd2 = os.path.join(self.t, "other", "dup")
        os.makedirs(cwd2); git("init", "-q", "-b", "main", cwd=cwd2)
        pd = os.path.join(self.proj_root, cwd2.replace("/", "-"), "memory")
        os.makedirs(pd); open(os.path.join(pd, "b.md"), "w").write("b")
        open(os.path.join(os.path.dirname(pd), "s.jsonl"), "w").write(json.dumps({"cwd": cwd2}) + "\n")
        ents, _ = mb.run_prv(self.proj_root, False, [], self.roster(a, cwd2), self.marks(a, cwd2))
        st = sorted(e["status"] for e in ents)
        self.assertEqual(st, ["ok", "skip"])
        self.assertIn("ad çakışması", [e for e in ents if e["status"] == "skip"][0]["reason"])

    def test_slug_and_gitlab_only(self):
        self.assertEqual(mb.slug("MIS 233 Web"), "MIS-233-Web")
        self.assertEqual(mb.targets_for("iggy"), ("gitlab",))
        self.assertEqual(mb.targets_for("x"), ("origin", "gitlab"))


class Visibility(Env):
    """13 Kas sahip revizyonu: -prv YALNIZ public repo ya da 'public olacak' işaretli proje için; private repoda hafıza kalır, DOKUNULMAZ."""

    def vis_run(self, vis):
        base = self.fake_run

        def run(argv, cwd=None, timeout=60):
            if argv[0] == "gh" and argv[1:3] == ["repo", "view"] and "--json" in argv and "visibility" in argv:
                return (0, json.dumps({"visibility": vis})) if vis else (1, "")
            return base(argv, cwd, timeout)
        return mock.patch.object(mb, "_run", run)

    def test_private_remote_untouched_not_flagged(self):
        cwd, _ = self.project("priv", remote="git@github.com:mfyuce/priv.git", tracked_memory=True)
        with self.vis_run("PRIVATE"):
            ents, _ = mb.run_prv(self.proj_root, True, [], self.roster(cwd), {})
        self.assertEqual(ents[0]["status"], "private")
        self.assertEqual(self.created, [])
        self.assertEqual(git("ls-files", "memory", cwd=cwd).strip(), "memory/old.md")        # git rm --cached YAPILMADI
        self.assertFalse(os.path.exists(mb.gitdir_of("priv")))

    def test_public_remote_gets_prv(self):
        cwd, _ = self.project("pub", remote="git@github.com:mfyuce/pub.git")
        with self.vis_run("PUBLIC"):
            ents, failed = mb.run_prv(self.proj_root, True, [], self.roster(cwd), {})
        self.assertEqual(failed, 0, ents[0].get("result"))
        self.assertEqual(ents[0]["why"], "public repo")
        self.assertEqual(sorted(k for k, _, _ in self.created), ["github", "gitlab"])

    def test_unverifiable_visibility_skips(self):
        cwd, _ = self.project("unk", remote="git@github.com:mfyuce/unk.git")
        with self.vis_run(None):
            ents, _ = mb.run_prv(self.proj_root, False, [], self.roster(cwd), {})
        self.assertIn("doğrulanamadı", ents[0]["reason"])

    def test_no_remote_and_company_are_private_no_action(self):
        a, _ = self.project("local_only")
        b, _ = self.project("corp", remote="git@git.corp.example:t/corp.git")
        ents, _ = mb.run_prv(self.proj_root, False, [], self.roster(a, b), {})
        self.assertEqual([e["status"] for e in ents], ["private", "private"])

    def test_flagged_private_repo_gets_prv_with_custom_name(self):
        cwd, _ = self.project("v1", remote="git@github.com:mfyuce/v1.git")
        with self.vis_run("PRIVATE"):
            ents, failed = mb.run_prv(self.proj_root, True, [], {os.path.realpath(cwd): "mecdtfl"}, {"mecdtfl": "mecdtfl-prv"})
        self.assertEqual(failed, 0, ents[0].get("result"))
        self.assertEqual(ents[0]["name"], "mecdtfl")
        self.assertEqual(ents[0]["why"], "public olacak işareti")
        self.assertEqual(sorted(n for _, n, _ in self.created), ["mecdtfl-prv", "mecdtfl-prv"])

    def test_mark_cli_roundtrip(self):
        from claudeops import settings
        saved = {}
        with mock.patch.object(settings, "save_settings", side_effect=lambda p: saved.update(p)):
            mb.run(mock.Mock(mark_public="mecdtfl=mecdtfl-prv", unmark_public="", apply=False, dry_run=False, only="", legacy_repo=False))
            self.assertEqual(saved["memory_prv_public"], {"mecdtfl": "mecdtfl-prv"})
            mb.run(mock.Mock(mark_public="", unmark_public="mecdtfl", apply=False, dry_run=False, only="", legacy_repo=False))
            self.assertEqual(saved["memory_prv_public"], {"mecdtfl": ""})


class Apply(Env):
    def test_apply_creates_repos_untracks_and_pushes_both(self):
        cwd, _ = self.project("alpha", tracked_memory=True)
        ents, failed = mb.run_prv(self.proj_root, True, [], self.roster(cwd), self.marks(cwd))
        self.assertEqual(failed, 0, ents[0].get("result"))
        self.assertEqual(sorted(self.created), [("github", "alpha-prv", True), ("gitlab", "alpha-prv", True)])
        # ana repo: memory takip dışı + exclude'da; ana repo geçmişine yeni memory dosyası GİRMEDİ
        self.assertEqual(git("ls-files", "memory", cwd=cwd).strip(), "")
        self.assertIn("/memory/", open(os.path.join(cwd, ".git", "info", "exclude")).read())
        self.assertEqual(git("status", "--porcelain", cwd=cwd).strip(), "")
        # -prv: iki remote'ta a.md + README var, old.md yok
        for kind in ("github", "gitlab"):
            files = git("--git-dir", os.path.join(self.remotes, kind, "alpha-prv.git"), "ls-tree", "-r", "--name-only", "main").split()
            self.assertIn("memory/a.md", files)
            self.assertIn("memory/README.md", files)
        self.assertTrue(os.path.isfile(mb.CREATED_LOG))

    def test_second_apply_is_noop(self):
        cwd, _ = self.project("alpha")
        mb.run_prv(self.proj_root, True, [], self.roster(cwd), self.marks(cwd))
        before = len(self.created)
        ents, failed = mb.run_prv(self.proj_root, True, [], self.roster(cwd), self.marks(cwd))
        self.assertEqual(failed, 0)
        self.assertEqual(len(self.created), before)
        self.assertEqual(ents[0]["prv_state"], "var")
        self.assertEqual(ents[0].get("result"), "değişiklik yok")

    def test_existing_remote_repo_is_not_recreated_history_kept(self):
        cwd, _ = self.project("delta")
        for kind in ("github", "gitlab"):
            d = self.bare(kind, "delta-prv")
            seed = os.path.join(self.t, "seed_" + kind)
            subprocess.run(["git", "clone", "-q", d, seed], check=True, capture_output=True)
            open(os.path.join(seed, "keep.txt"), "w").write("k")
            git("add", "keep.txt", cwd=seed)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed"], cwd=seed, check=True)
            git("push", "-q", "origin", "HEAD:main", cwd=seed)
        self.existing = {"mfyuce/delta-prv"}
        ents, failed = mb.run_prv(self.proj_root, True, [], self.roster(cwd), self.marks(cwd))
        self.assertEqual(failed, 0, ents[0].get("result"))
        self.assertEqual(self.created, [])
        files = git("--git-dir", os.path.join(self.remotes, "github", "delta-prv.git"), "ls-tree", "-r", "--name-only", "main").split()
        self.assertIn("keep.txt", files)                      # eski geçmiş korundu
        self.assertIn("memory/a.md", files)

    def test_company_repo_untrack_not_pushed(self):
        corp = os.path.join(self.t, "corp_remote.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", corp], check=True)
        cwd, _ = self.project("corp", remote="git@git.corp.example:team/corp.git", tracked_memory=True)
        ents, failed = mb.run_prv(self.proj_root, True, [], self.roster(cwd), self.marks(cwd))
        self.assertEqual(failed, 0, ents[0].get("result"))
        self.assertIn("şirket repo", ents[0]["result"])
        self.assertEqual(git("remote", "get-url", "origin", cwd=cwd).strip(), "git@git.corp.example:team/corp.git")

    def test_iggy_gitlab_only(self):
        cwd, _ = self.project("iggy")
        ents, failed = mb.run_prv(self.proj_root, True, [], self.roster(cwd), self.marks(cwd))
        self.assertEqual(failed, 0, ents[0].get("result"))
        self.assertEqual([k for k, _, _ in self.created], ["gitlab"])
        self.assertNotIn("origin", git("--git-dir", mb.gitdir_of("iggy"), "remote").split())


class Cli(Env):
    def test_default_is_prv_dry_run(self):
        cwd, _ = self.project("alpha")
        with mock.patch.object(mb, "PROJECTS_ROOT", self.proj_root), mock.patch.object(mb, "roster_cwds", return_value=self.roster(cwd)), mock.patch.object(mb, "public_marks", return_value=self.marks(cwd)), \
             mock.patch("builtins.print") as pr:
            rc = mb.run(mock.Mock(apply=False, dry_run=False, only="", legacy_repo=False, mark_public="", unmark_public=""))
        self.assertEqual(rc, 0)
        self.assertIn("-prv kipi", pr.call_args[0][0])
        self.assertEqual(self.created, [])


if __name__ == "__main__":
    unittest.main()


class PeriodicJob(unittest.TestCase):
    def test_job_registered_default_off_and_summarizes(self):
        from claudeops import periodic as P
        self.assertEqual(P.load_config()["memory_prv"]["enabled"], "off")
        ents = [{"status": "ok", "name": "a", "result": "yedeklendi (1 dosya, 2 remote doğrulandı)", "creates": [("github", "a-prv", False)]},
                {"status": "skip", "proj": "hc", "roster_name": "hc", "reason": "sır taraması: x.md: password= (sahibe bildir)"}]
        with mock.patch.object(mb, "run_prv", return_value=(ents, 0)):
            res = P.run_memory_prv({}, True, {})
        self.assertTrue(res["ok"])
        self.assertIn("oluşturulan: a-prv", res["msg"])
        self.assertIn("SIR TARAMASINDA TAKILAN: hc", res["msg"])

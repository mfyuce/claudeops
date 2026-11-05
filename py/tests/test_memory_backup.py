"""memory-backup: sahte repo/gh/glab (mm._run yamalı), geçici dizinler; gerçek ağ ve gerçek ~/.claude YOK."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import memory_backup as mm  # noqa: E402


class Fake:
    def __init__(self, repo, remotes, vis=None, top=None, head="abc123", ls_ok=True, behind=(), dirty="", merge_rc=0):
        self.repo, self.remotes, self.vis = repo, remotes, vis or {}
        self.top = repo if top is None else top
        self.head, self.ls_ok = head, ls_ok
        self.behind, self.dirty, self.merge_rc = set(behind), dirty, merge_rc
        self.calls = []

    def __call__(self, argv, cwd=None, timeout=60):
        self.calls.append(list(argv))
        a = argv
        if a[:2] == ["git", "merge-base"]:
            return (1 if a[3].split("/")[0] in self.behind else 0), ""
        if a[:2] == ["git", "status"]:
            return 0, self.dirty
        if a[:2] == ["git", "merge"]:
            return (self.merge_rc, "") if a[2] != "--abort" else (0, "")
        if a[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return (0, self.top + "\n") if self.top else (128, "")
        if a[:3] == ["git", "remote", "-v"]:
            return 0, "".join(f"{n}\t{u} (fetch)\n{n}\t{u} (push)\n" for n, u in self.remotes.items())
        if a[0] in ("gh", "glab"):
            path = a[3]
            return 0, json.dumps({"visibility": self.vis.get(path, "public")})
        if a[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return 0, "main\n"
        if a[:3] == ["git", "rev-parse", "HEAD"]:
            return 0, self.head + "\n"
        if a[:2] == ["git", "ls-remote"]:
            return 0, (self.head if self.ls_ok else "dead") + "\trefs/heads/main\n"
        return 0, ""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "projects")
        self.repo = os.path.join(self.tmp.name, "wifi")
        os.makedirs(self.repo)

    def proj(self, name="p1", cwd=None, files=None, jsonl=True):
        pd = os.path.join(self.root, name)
        os.makedirs(os.path.join(pd, "memory"))
        if jsonl:
            with open(os.path.join(pd, "s.jsonl"), "w") as f:
                f.write("not json\n" + json.dumps({"type": "x", "cwd": cwd or self.repo}) + "\n")
        for k, v in (files or {"MEMORY.md": "- idx\n"}).items():
            with open(os.path.join(pd, "memory", k), "w") as f:
                f.write(v)
        return pd

    def run_bk(self, fake, apply=False, only=()):
        with mock.patch.object(mm, "_run", fake):
            return mm.run_backup(self.root, apply, list(only))


class Tests(Base):
    GH = {"github": "git@github.com:me/wifi.git"}

    def test_parse_remote(self):
        self.assertEqual(mm.parse_remote("git@github.com:me/x.git"), ("github", "me/x"))
        self.assertEqual(mm.parse_remote("https://gitlab.com/g/sub/x.git"), ("gitlab", "g/sub/x"))
        self.assertIsNone(mm.parse_remote("git@git.corp.local:me/x.git"))

    def test_no_cwd_skipped(self):
        self.proj(jsonl=False)
        ents, _ = self.run_bk(Fake(self.repo, self.GH))
        self.assertEqual(ents[0]["reason"], "cwd bulunamadı")

    def test_not_repo_root_and_no_repo(self):
        self.proj()
        ents, _ = self.run_bk(Fake(self.repo, self.GH, top=os.path.dirname(self.repo)))
        self.assertEqual(ents[0]["reason"], "cwd repo kökü değil")
        ents, _ = self.run_bk(Fake(self.repo, self.GH, top=""))
        self.assertEqual(ents[0]["reason"], "git repo yok")

    def test_public_or_corp_remote_skipped(self):
        self.proj()
        ents, _ = self.run_bk(Fake(self.repo, self.GH, vis={"me/wifi": "public"}))
        self.assertTrue(ents[0]["reason"].startswith("sahibe sor"))
        ents, _ = self.run_bk(Fake(self.repo, {"o": "git@git.corp.local:me/x.git"}))
        self.assertIn("şirket içi", ents[0]["reason"])

    def test_one_public_remote_among_private_skips(self):
        self.proj()
        rem = {"github": "git@github.com:me/wifi.git", "gitlab": "git@gitlab.com:me/wifi.git"}
        ents, _ = self.run_bk(Fake(self.repo, rem, vis={"me/wifi": "private"}))   # aynı yol: github private, gitlab da private
        self.assertEqual(ents[0]["status"], "ok")
        ents, _ = self.run_bk(Fake(self.repo, rem, vis={"me/wifi": "private", "x": "x"}), only=["nope"])
        self.assertEqual(ents, [])

    def test_secret_skips(self):
        self.proj(files={"a.md": "token ghp_" + "A" * 24, "b.md": "ok"})
        ents, _ = self.run_bk(Fake(self.repo, self.GH, vis={"me/wifi": "private"}), apply=True)
        self.assertTrue(ents[0]["reason"].startswith("sır taraması"))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "memory")))

    def test_secret_patterns(self):
        for t in ("-----BEGIN PRIVATE KEY-----", "sk-ant-abcdefgh12", "glpat-abcdefghij12", "AKIA" + "A" * 16, "password=hunter22"):
            self.assertTrue(mm.scan_secrets({"x": t}), t)
        self.assertFalse(mm.scan_secrets({"x": "password= <gizli> ve parola notu"}))

    def test_dry_run_writes_nothing(self):
        self.proj()
        f = Fake(self.repo, self.GH, vis={"me/wifi": "private"})
        ents, failed = self.run_bk(f)
        self.assertEqual(ents[0]["status"], "ok")
        self.assertEqual(failed, 0)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "memory")))
        self.assertFalse(any(c[:2] in (["git", "add"], ["git", "commit"], ["git", "push"]) for c in f.calls))
        self.assertIn("DRY-RUN", mm.render(ents, False))

    def test_apply_copies_commits_pushes_verifies(self):
        self.proj(files={"MEMORY.md": "a", "x.md": "b", "notes.txt": "no"})
        f = Fake(self.repo, self.GH, vis={"me/wifi": "private"})
        ents, failed = self.run_bk(f, apply=True)
        self.assertEqual(failed, 0, ents)
        d = os.path.join(self.repo, "memory")
        self.assertEqual(sorted(os.listdir(d)), ["MEMORY.md", "README.md", "x.md"])
        self.assertIn(self.root, open(os.path.join(d, "README.md")).read())
        add = next(c for c in f.calls if c[:2] == ["git", "add"])
        self.assertEqual(add, ["git", "add", "--", "memory/MEMORY.md", "memory/x.md", "memory/README.md"])
        self.assertNotIn("-A", add)
        self.assertTrue(any(c[:2] == ["git", "push"] for c in f.calls))
        self.assertTrue(any(c[:2] == ["git", "ls-remote"] for c in f.calls))

    def test_only_unchanged_files_and_second_run_noop(self):
        self.proj(files={"MEMORY.md": "a"})
        f = Fake(self.repo, self.GH, vis={"me/wifi": "private"})
        self.run_bk(f, apply=True)
        f2 = Fake(self.repo, self.GH, vis={"me/wifi": "private"})
        ents, _ = self.run_bk(f2, apply=True)
        self.assertEqual(ents[0]["result"], "değişiklik yok")
        self.assertFalse(any(c[:2] == ["git", "commit"] for c in f2.calls))

    def test_ls_remote_mismatch_is_failure(self):
        self.proj()
        ents, failed = self.run_bk(Fake(self.repo, self.GH, vis={"me/wifi": "private"}, ls_ok=False), apply=True)
        self.assertEqual(failed, 1)
        self.assertIn("ls-remote", ents[0]["result"])

    PRIV = {"me/wifi": "private"}

    def test_empty_source_skipped(self):
        self.proj(files={"README.md": "x"})
        f = Fake(self.repo, self.GH, vis=self.PRIV)
        ents, _ = self.run_bk(f, apply=True)
        self.assertEqual(ents[0]["reason"], "kaynak boş")
        self.assertFalse(any(c[:2] == ["git", "commit"] for c in f.calls))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "memory")))

    def test_remote_ahead_clean_merges_before_push(self):
        self.proj()
        f = Fake(self.repo, self.GH, vis=self.PRIV, behind=["github"])
        ents, failed = self.run_bk(f, apply=True)
        self.assertEqual(failed, 0, ents)
        names = [c[:2] for c in f.calls]
        self.assertIn(["git", "fetch"], names)
        merge = next(c for c in f.calls if c[:2] == ["git", "merge"])
        self.assertEqual(merge, ["git", "merge", "--no-edit", "github/main"])
        self.assertFalse(any(c[:2] == ["git", "rebase"] for c in f.calls))
        self.assertLess(names.index(["git", "merge"]), names.index(["git", "push"]))

    def test_remote_ahead_dirty_tree_skips_remote(self):
        self.proj()
        f = Fake(self.repo, self.GH, vis=self.PRIV, behind=["github"], dirty=" M x.py\n")
        ents, failed = self.run_bk(f, apply=True)
        self.assertEqual(failed, 1)
        self.assertIn("elle birleştir", ents[0]["result"])
        self.assertFalse(any(c[:2] in (["git", "merge"], ["git", "push"]) for c in f.calls))

    def test_merge_conflict_aborts_and_skips(self):
        self.proj()
        f = Fake(self.repo, self.GH, vis=self.PRIV, behind=["github"], merge_rc=1)
        ents, failed = self.run_bk(f, apply=True)
        self.assertEqual(failed, 1)
        self.assertIn(["git", "merge", "--abort"], f.calls)
        self.assertFalse(any(c[:2] == ["git", "push"] for c in f.calls))

    def test_not_ahead_no_merge(self):
        self.proj()
        f = Fake(self.repo, self.GH, vis=self.PRIV)
        self.run_bk(f, apply=True)
        self.assertFalse(any(c[:2] == ["git", "merge"] for c in f.calls))

    def test_cwd_from_chat_mirror(self):
        pd = self.proj("p-mirror", jsonl=False)
        mroot = os.path.join(self.tmp.name, "mirror")
        md = os.path.join(mroot, "p-mirror")
        os.makedirs(md)
        with open(os.path.join(md, "s.jsonl"), "w") as fh:
            fh.write(json.dumps({"cwd": "/some/where"}) + "\n")
        with mock.patch.object(mm, "MIRROR_ROOT", mroot):
            self.assertEqual(mm.read_cwd(pd), "/some/where")
        with mock.patch.object(mm, "MIRROR_ROOT", os.path.join(self.tmp.name, "yok")):
            self.assertEqual(mm.read_cwd(pd), "")

    def test_only_filter(self):
        self.proj("p1")
        ents, _ = self.run_bk(Fake(self.repo, self.GH, vis={"me/wifi": "private"}), only=["wifi"])
        self.assertEqual(len(ents), 1)
        ents, _ = self.run_bk(Fake(self.repo, self.GH, vis={"me/wifi": "private"}), only=["baska"])
        self.assertEqual(ents, [])


if __name__ == "__main__":
    unittest.main()

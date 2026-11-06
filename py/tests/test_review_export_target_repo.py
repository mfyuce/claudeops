"""GATE-TODO4 madde 1: review export bulgunun YOLUNA gore dogru repoya yazar; combo dizinine (git degil) yazmaz.
Gecici dizinler, gercek Popen/ag yok. Calistirma: python3 -m unittest discover -s py/tests"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_review_findings_flow import _Flow, T1  # noqa: E402
from claudeops import review as rv  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402


def _repo(root, name):
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, ".git"))
    return d


class TestExportRootPure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_prefix_resolves_to_registered_repo(self):
        combo = os.path.join(self.root, "combo")
        os.makedirs(os.path.join(combo, "unified-cli"))        # combo kopyasi, git degil
        uni = _repo(self.root, "unified-cli")
        res = lambda n: uni if n == "unified-cli" else ""      # noqa: E731
        row = {"where": "unified-cli/src/a.rs:3"}
        self.assertEqual(rv.export_root(row, "cliops", combo, res), uni)

    def test_combo_without_target_is_unresolved(self):
        combo = os.path.join(self.root, "combo")
        os.makedirs(os.path.join(combo, "uzakgoz"))
        self.assertEqual(rv.export_root({"where": "uzakgoz/x.py:1"}, "uzops", combo, lambda n: ""), "")

    def test_git_cwd_and_no_prefix_keep_old_behaviour(self):
        repo = _repo(self.root, "claudeops")
        self.assertEqual(rv.export_root({"where": "claudeops/py/a.py:1"}, "claudeops", repo, lambda n: ""), repo)
        plain = os.path.join(self.root, "plain")
        os.makedirs(plain)
        self.assertEqual(rv.export_root({"where": "x.py:1"}, "p", plain, lambda n: ""), plain)


class TestComboWorktree(unittest.TestCase):
    """Combo alt dizini ana deponun worktree'si: depo adi kayitli proje adi olmasa da (claudeops=cops) ana depoya yazilir."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.main = _repo(self.tmp.name, "claudeops")
        self.combo = os.path.join(self.tmp.name, "combo")
        wt = os.path.join(self.combo, "claudeops")
        os.makedirs(wt)
        with open(os.path.join(wt, ".git"), "w", encoding="utf-8") as f:
            f.write(f"gitdir: {self.main}/.git/worktrees/claudeops\n")

    def test_worktree_prefix_resolves_to_main_repo(self):
        self.assertEqual(rv.export_root({"where": "claudeops/py/a.py:1"}, "cliops", self.combo, lambda n: ""), self.main)

    def test_non_worktree_git_file_is_not_followed(self):
        wt = os.path.join(self.combo, "sub")
        os.makedirs(wt)
        with open(os.path.join(wt, ".git"), "w", encoding="utf-8") as f:
            f.write("gitdir: /nowhere/modules/sub\n")
        self.assertEqual(rv.export_root({"where": "sub/a.py:1"}, "cliops", self.combo, lambda n: ""), "")

    def test_staleness_checks_the_real_repo_not_the_snapshot(self):
        os.makedirs(os.path.join(self.main, "py"))
        with open(os.path.join(self.main, "py", "a.py"), "w", encoding="utf-8") as f:
            f.write("def yeni(): pass\n")
        row = {"where": "claudeops/py/a.py:1", "title": "`eski` hatali"}
        chk, root = rv.row_in_repo(row, self.main, self.combo)
        self.assertEqual((chk["where"], root), ("py/a.py:1", self.main))
        self.assertTrue(rv.stale_reason(chk, root))
        same = {"where": "py/a.py:1"}
        self.assertEqual(rv.row_in_repo(same, self.main, self.main), (same, self.main))


class TestExportRoutesByPath(_Flow):
    MD = ("## R-1 | P2 | unified-cli/src/a.rs:1 | Birinci\ngovde\n\n"
          "## R-2 | P2 | zzz/b.py:2 | Ikinci\ngovde\n")

    def _approve_all(self, fids):
        d = self.findings()
        for f in fids:
            d[f]["state"] = "approved"
        rv.save_findings(self.p, d)

    def test_writes_to_path_repo_and_warns_for_unresolved(self):
        os.makedirs(os.path.join(self.proj_dir, "zzz"))          # combo gibi: alt dizin var, proje git degil
        uni = _repo(self.dir.name, "unified-cli")
        fids = self.seed(self.MD)
        self._approve_all(fids)
        cwd_map = lambda n: self.proj_dir if n == "a" else (uni if n == "unified-cli" else "")  # noqa: E731
        with mock.patch.object(wr, "project_cwd", cwd_map):
            res = wr.export_findings(self.cfg_(), "a", "TODO.md", now=5_000.0)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["written"], [fids[0]])
        self.assertTrue(os.path.isfile(os.path.join(uni, "TODO.md")))
        self.assertFalse(os.path.exists(os.path.join(self.proj_dir, "TODO.md")))
        self.assertIn("hedef git deposu bulunamadı", res["warning"])
        self.assertEqual(res["unresolved"], [fids[1]])
        st = {k: v["state"] for k, v in self.findings().items()}
        self.assertEqual(st[fids[0]], "exported")
        self.assertEqual(st[fids[1]], "approved")                # kaybolmaz, yeniden denenebilir

    def test_nothing_resolvable_writes_nothing(self):
        os.makedirs(os.path.join(self.proj_dir, "zzz"))
        fids = self.seed("## R-2 | P2 | zzz/b.py:2 | Ikinci\ngovde\n")
        self._approve_all(fids)
        res = wr.export_findings(self.cfg_(), "a", "TODO.md", now=5_000.0)
        self.assertFalse(res["ok"])
        self.assertIn("warning", res)
        self.assertFalse(os.path.exists(os.path.join(self.proj_dir, "TODO.md")))

    def cfg_(self):
        from claudeops.commands import web_steward as ws
        return ws.steward_config("rev")


if __name__ == "__main__":
    unittest.main()

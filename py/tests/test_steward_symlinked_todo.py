"""Worktree projesinin TODO.md'si başka kayıtlı projenin TODO.md'sine symlink ise (scripts/worktree-docs-link.sh): sayı o projeye ait
DEĞİL, `_open_work_of` None (bilinmiyor) döner; böylece kanıtlı STEWARD-DONE-CONFIRMED çelişki sorusuna dönmez. Canlı servis YOK."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class SymlinkedTodo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.main, self.wt, self.lone = (os.path.join(d, n) for n in ("main", "wt", "lone"))
        for p in (self.main, self.lone):
            os.mkdir(p)
            subprocess.run(["git", "init", "-q", p], check=True)
            with open(os.path.join(p, "TODO.md"), "w", encoding="utf-8") as f:
                f.write("- [ ] a\n- [ ] b\n- [ ] c\n")
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "-C", self.main, "add", "."], check=True)
        subprocess.run(["git", "-C", self.main, "commit", "-qm", "i"], check=True, env=env)
        subprocess.run(["git", "-C", self.main, "worktree", "add", "-q", "-b", "wtb", self.wt], check=True)
        os.remove(os.path.join(self.wt, "TODO.md"))     # git worktree'de izlenen kopya var; derbent düzeni: symlink
        os.symlink(os.path.join(self.main, "TODO.md"), os.path.join(self.wt, "TODO.md"))
        self.projs = {n: sw.Project(name=n, phase="planned") for n in ("cops", "copsdevderbent", "lone")}
        self.cwds = {"cops": self.main, "copsdevderbent": self.wt, "lone": self.lone}
        self.orig = ws._cwd_resolver
        ws._cwd_resolver = lambda: (lambda n: self.cwds.get(n, ""))

    def tearDown(self):
        ws._cwd_resolver = self.orig
        self.tmp.cleanup()

    def test_symlinked_worktree_without_tagged_lines_is_unknown(self):
        self.assertIsNone(ws._open_work_of(self.projs)("copsdevderbent"))
        self.assertIsNone(ws._scan_todo(self.projs, "copsdevderbent"))

    def test_owner_main_checkout_still_counts(self):
        self.assertEqual(ws._open_work_of(self.projs)("cops"), 3)
        self.assertEqual(ws._open_work_of(self.projs)("lone"), 3)

    def test_symlinked_worktree_counts_its_tagged_lines(self):
        """rsprov 28 Kas: ortak TODO'da `(rs-prov, ...)` açık maddeler varken 'iş yok' diye paused yapıldı (sayı None idi)."""
        with open(os.path.join(self.main, "TODO.md"), "a", encoding="utf-8") as f:
            f.write("- [ ] (copsdevderbent, edge) x\n- [ ] (26 Kas, copsdev-derbent; kapı: cops) y\n- [x] (copsdevderbent) bitti\n"
                    "- [ ] (cops, copsdevderbentx) başkası\n- [ ] (sahip cevabı, copsdevderbent) SAHİPTE z\n")
        self.assertEqual(ws._scan_todo(self.projs, "copsdevderbent"), (2, 1))
        self.assertEqual(ws._open_work_of(self.projs)("cops"), 6)      # sahibi hepsini sayar (sahibe bağlı hariç)

    def test_same_cwd_extension_project_is_shared(self):
        """copsdevderbent 28 Kas: cwd ana checkout (cops ile aynı), claudeops'un 435 maddesini kendi işi sandı."""
        self.cwds["copsdevderbent"] = self.main
        self.assertIsNone(ws._open_work_of(self.projs)("copsdevderbent"))
        self.assertEqual(ws._open_work_of(self.projs)("cops"), 3)
        with open(os.path.join(self.main, "TODO.md"), "a", encoding="utf-8") as f:
            f.write("- [ ] (copsdevderbent) x\n")
        self.assertEqual(ws._open_work_of(self.projs)("copsdevderbent"), 1)
        self.assertEqual(ws._open_work_of(self.projs)("cops"), 4)

    def test_same_cwd_unrelated_names_keep_counting(self):
        self.cwds["lone"] = self.main       # adı diğerinin uzantısı değil: eski davranış
        self.assertEqual(ws._open_work_of(self.projs)("lone"), 3)

    def test_symlink_to_unregistered_dir_still_counts(self):
        del self.projs["cops"]      # ana checkout kayıtlı proje değil: eski davranış (sayılır)
        self.assertEqual(ws._open_work_of(self.projs)("copsdevderbent"), 3)


if __name__ == "__main__":
    unittest.main()

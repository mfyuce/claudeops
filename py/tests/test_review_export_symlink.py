"""Dışa aktarım worktree'deki not bağını (TODO.md -> ana checkout) koparmaz; beklenmeyen bağa yazmaz (27 Kas)."""
import os
import tempfile
import unittest

from claudeops.commands import web_review as wr


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class ExportWritePathTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = os.path.realpath(tmp.name)
        self.main = os.path.join(self.base, "main")
        self.wt = os.path.join(self.base, "wt")
        os.makedirs(os.path.join(self.main, ".git", "worktrees", "wt"))
        os.makedirs(self.wt)
        _write(os.path.join(self.wt, ".git"), f"gitdir: {self.main}/.git/worktrees/wt\n")
        self.notes = os.path.join(self.main, "TODO.md")
        _write(self.notes, "ana\n")
        self.link = os.path.join(self.wt, "TODO.md")

    def test_plain_file_and_missing_file_keep_path(self):
        self.assertEqual(wr._export_write_path(self.wt, "TODO.md"), self.link)
        self.assertEqual(wr._export_write_path(self.main, "TODO.md"), self.notes)

    def test_worktree_note_link_resolves_to_main_file(self):
        os.symlink(self.notes, self.link)
        self.assertEqual(wr._export_write_path(self.wt, "TODO.md"), self.notes)
        self.assertTrue(os.path.islink(self.link))

    def test_unexpected_links_are_refused(self):
        other = os.path.join(self.base, "TODO.md")
        _write(other, "yabanci\n")
        for dest in (other, os.path.join(self.main, "yok", "TODO.md")):
            os.symlink(dest, self.link)
            self.assertEqual(wr._export_write_path(self.wt, "TODO.md"), "", dest)
            os.remove(self.link)

    def test_link_in_non_worktree_is_refused(self):
        plain = os.path.join(self.base, "plain")
        os.makedirs(plain)
        os.symlink(self.notes, os.path.join(plain, "TODO.md"))
        self.assertEqual(wr._export_write_path(plain, "TODO.md"), "")


if __name__ == "__main__":
    unittest.main()

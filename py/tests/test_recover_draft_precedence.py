"""_recover_draft: stdout rapor taşımıyorsa taslak/bulgu dosyası kazanır; rapor taşıyorsa stdout (review cops 2 Kas)."""
import os
import tempfile
import unittest

from claudeops.commands import web_review as wr
from claudeops import review as rv

REPORT = "## R-1 | P2 | a.py:1 | başlık\ngövde\n"


class Precedence(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "20261114000000.md")
        open(rv.draft_path(self.path), "w").write(REPORT)

    def test_chatty_stdout_loses_to_draft(self):
        text, from_draft = wr._recover_draft(self.path, "Bitirdim, rapor dosyada.\n")
        self.assertTrue(from_draft)
        self.assertIn("## R-1 |", text)

    def test_stdout_with_report_wins(self):
        out = "## R-9 | P3 | b.py:2 | x\n"
        self.assertEqual(wr._recover_draft(self.path, out), (out, False))

    def test_empty_stdout_uses_draft(self):
        text, from_draft = wr._recover_draft(self.path, "")
        self.assertTrue(from_draft and "## R-1 |" in text)

    def test_no_draft_keeps_stdout(self):
        os.remove(rv.draft_path(self.path))
        self.assertEqual(wr._recover_draft(self.path, "merhaba"), ("merhaba", False))


if __name__ == "__main__":
    unittest.main()

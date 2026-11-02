"""TBD#142: qa_log.append_qa — yalnız var olan <local_path>-prv/SORU-CEVAP.md'ye tek satır ekler.

Çalıştırma:  python3 py/tests/test_qa_log.py -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import qa_log  # noqa: E402


class QaLog(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.lp = os.path.join(self.root, "proj")
        os.makedirs(self.lp + "-prv")
        self.f = os.path.join(self.lp + "-prv", "SORU-CEVAP.md")

    def test_no_file_no_create(self):
        self.assertFalse(qa_log.append_qa(self.lp, "answer", "cli", "x"))
        self.assertFalse(os.path.exists(self.f))

    def test_empty_local_path_skips(self):
        self.assertFalse(qa_log.append_qa("", "answer", "cli", "x"))
        self.assertIsNone(qa_log.qa_path(""))

    def test_appends_single_line_with_actor(self):
        with open(self.f, "w") as fh:
            fh.write("# SORU-CEVAP\n")
        self.assertTrue(qa_log.append_qa(self.lp, "answer", "cli", "evet\nçok satır\n\nson", ref="q1", now=0))
        self.assertTrue(qa_log.append_qa(self.lp, "directive", "brain", "devam", now=0))
        lines = open(self.f, encoding="utf-8").read().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("[answer] cli (q1): evet çok satır son", lines[1])
        self.assertIn("[directive] brain: devam", lines[2])

    def test_long_text_truncated(self):
        with open(self.f, "w") as fh:
            fh.write("")
        qa_log.append_qa(self.lp, "answer", "a", "z" * 5000)
        self.assertLess(len(open(self.f).read()), 700)

    def test_write_error_returns_false(self):
        with open(self.f, "w") as fh:
            fh.write("")
        os.chmod(self.f, 0o400)
        try:
            if os.geteuid() != 0:
                self.assertFalse(qa_log.append_qa(self.lp, "answer", "a", "x"))
        finally:
            os.chmod(self.f, 0o600)


if __name__ == "__main__":
    unittest.main()

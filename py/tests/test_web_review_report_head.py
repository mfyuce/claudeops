"""web_review._REPORT_HEAD_RE: `BULGU YOK` yalnız satır başında rapor sayılır (P3 #24)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_review  # noqa: E402


class ReportHeadTest(unittest.TestCase):
    def test_finding_heading(self):
        self.assertTrue(web_review._REPORT_HEAD_RE.search("giris\n## R-1 | P2 | x"))

    def test_bulgu_yok_line(self):
        self.assertTrue(web_review._REPORT_HEAD_RE.search("inceledim\nBULGU YOK\n"))
        self.assertTrue(web_review._REPORT_HEAD_RE.search("BULGU YOK"))

    def test_sentence_mention_is_not_report(self):
        self.assertFalse(web_review._REPORT_HEAD_RE.search("bu bir sohbet: BULGU YOK demeyi unutma"))

    def test_garbage(self):
        self.assertFalse(web_review._REPORT_HEAD_RE.search("calisiyorum..."))


if __name__ == "__main__":
    unittest.main()

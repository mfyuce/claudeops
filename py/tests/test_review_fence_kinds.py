"""Kod çiti yalnız KENDİ türüyle kapanır: ``` içindeki ~~~ satırı çiti kapatmaz (parse_findings, scan_verdicts)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import review as rv  # noqa: E402


class FenceKindTest(unittest.TestCase):
    def test_fence_step(self):
        self.assertEqual(rv._fence_step("", "```py"), ("```", True))
        self.assertEqual(rv._fence_step("```", "~~~"), ("```", True))
        self.assertEqual(rv._fence_step("```", "```"), ("", True))
        self.assertEqual(rv._fence_step("~~~", "```"), ("~~~", True))
        self.assertEqual(rv._fence_step("", "düz"), ("", False))

    def test_tilde_inside_backtick_fence_does_not_reopen_findings(self):
        md = "```\n~~~\n## R-1 | P1 | a.py:1 | sahte\n```\n## R-2 | P2 | b.py:2 | gercek\n"
        self.assertEqual([f["ref"] for f in rv.parse_findings(md)], ["R-2"])

    def test_tilde_inside_backtick_fence_does_not_leak_verdict(self):
        txt = "```\n~~~\nSTEWARD-REVIEW-VERDICT: F1 verified sahte\n```\nSTEWARD-REVIEW-VERDICT: F2 verified gercek\n"
        self.assertEqual([v[0] for v in rv.scan_verdicts(txt)], ["F2"])


if __name__ == "__main__":
    unittest.main()

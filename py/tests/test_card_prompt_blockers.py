"""Kart promptu bayat engel taşımasın: 'blockers' yalnız şu an açık görünenleri içersin (tr+en)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import steward as sw  # noqa: E402


class CardPromptBlockersTest(unittest.TestCase):
    def test_tr_prompt_demands_currently_open_blockers(self):
        p = sw.build_card_prompt("ncs", {"docs": {"PLAN.md": "x"}}, lang="tr")
        self.assertIn("ŞU AN açık", p)

    def test_en_prompt_demands_currently_open_blockers(self):
        p = sw.build_card_prompt("ncs", {"docs": {"PLAN.md": "x"}}, lang="en")
        self.assertIn("open NOW", p)


if __name__ == "__main__":
    unittest.main()

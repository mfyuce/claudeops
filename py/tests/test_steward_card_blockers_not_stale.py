"""GATE-TODO3 #5b: kart yenilemede eski `blockers` satirlari tasinmaz (yalniz taze ayristirmadan gelir; ham kartta bos).
Calistirma:  python3 py/tests/test_steward_card_blockers_not_stale.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import steward as sw  # noqa: E402

RAW = {"docs": {}, "git_log": [], "last_commit": 1.0, "source_hash": "h"}


class CardBlockersNotStale(unittest.TestCase):
    def test_raw_card_has_no_blockers(self):
        self.assertEqual(sw.raw_card_fields(RAW)["blockers"], [])

    def test_make_card_without_parse_has_empty_blockers(self):
        card = sw.make_card(RAW, None, None, now=5.0)
        self.assertEqual(card["blockers"], [])
        self.assertFalse(card["summarized"])

    def test_fresh_parse_without_blockers_does_not_inherit_old(self):
        # parsed bos blockers listesi tasir: eski karttan (burada hic verilmez) devralinmaz
        parsed = {"goal": "g", "phase_guess": "", "next_step": "n", "open_tbds": [], "blockers": [], "recent_done": []}
        card = sw.make_card(RAW, parsed, None, now=5.0)
        self.assertEqual(card["blockers"], [])

    def test_fresh_parse_blockers_are_used(self):
        parsed = {"goal": "g", "phase_guess": "", "next_step": "n", "open_tbds": [], "blockers": ["yeni engel"], "recent_done": []}
        card = sw.make_card(RAW, parsed, None, now=5.0)
        self.assertEqual(card["blockers"], ["yeni engel"])


if __name__ == "__main__":
    unittest.main()

"""TBD#163 (g) yazım haritası = onay ve (h) sahip cevabı yorumu: beyin kural metninde bulunur (TR+EN)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402


class TestBrainRules(unittest.TestCase):
    def test_rules_present_in_both_languages(self):
        self.assertIn("YAZIM HARİTASI = ONAY", sw.MODEL_RULE_TR)
        self.assertIn("anladığım:", sw.MODEL_RULE_TR)
        self.assertIn("WRITING MAP = APPROVAL", sw.MODEL_RULE_EN)
        self.assertIn("understood:", sw.MODEL_RULE_EN)

    def test_h_is_limited_to_reversible_questions(self):
        self.assertIn("GERİ ALINABİLİR", sw.MODEL_RULE_TR)
        self.assertIn("REVERSIBLE", sw.MODEL_RULE_EN)


if __name__ == "__main__":
    unittest.main()

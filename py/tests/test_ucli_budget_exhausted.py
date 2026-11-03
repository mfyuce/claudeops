"""563: `budget_exhausted` cevabı kısmi diye işaretlenir (saf; ağ/süreç YOK)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_client as uc  # noqa: E402


class BudgetExhaustedTest(unittest.TestCase):
    def test_failures_prefixes_answer_once(self):
        v = uc.mark_budget_exhausted({"answer": "yarım", "budget_exhausted": "failures"})
        self.assertTrue(v["answer"].startswith("[⚠ "))
        self.assertTrue(v["answer"].endswith("yarım"))
        again = uc.mark_budget_exhausted(dict(v))
        self.assertEqual(again["answer"].count("[⚠ "), 1)

    def test_unknown_reason_still_marked(self):
        v = uc.mark_budget_exhausted({"answer": "x", "budget_exhausted": "steps"})
        self.assertIn("steps", v["answer"])

    def test_no_field_unchanged(self):
        v = {"answer": "tam"}
        self.assertEqual(uc.mark_budget_exhausted(v), {"answer": "tam"})
        # boş/None alan: değer AYNEN döner (alan düşürülmez; docstring sözleşmesi), answer'a uyarı eklenmez
        self.assertEqual(uc.mark_budget_exhausted({"answer": "t", "budget_exhausted": None}),
                         {"answer": "t", "budget_exhausted": None})

    def test_parse_turn_marks(self):
        v = uc._parse_turn(json.dumps({"answer": "a", "budget_exhausted": "failures"}))
        self.assertTrue(v["answer"].startswith("[⚠ "))


if __name__ == "__main__":
    unittest.main()

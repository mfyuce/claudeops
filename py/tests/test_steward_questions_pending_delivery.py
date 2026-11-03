"""GATE-TODO3 #6: cevapli ama `delivered_at` bos soru `steward questions` ciktisinda 'teslim bekliyor' gorunur.
Calistirma:  python3 py/tests/test_steward_questions_pending_delivery.py -v
"""
import os
import sys
import time
import unittest
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import steward as cs  # noqa: E402


def _q(status, delivered_at):
    return NS(id="q1", project="kitap", created_at=time.time() - 60, text="Hangisi?", status=status,
              delivered_at=delivered_at)


class QuestionHeadTests(unittest.TestCase):
    def test_answered_not_delivered_shows_pending(self):
        line = cs.question_head(_q("answered", 0))
        self.assertIn("teslim bekliyor", line)
        self.assertTrue(line.startswith("…"))

    def test_answered_delivered_has_no_pending_label(self):
        line = cs.question_head(_q("answered", time.time()))
        self.assertNotIn("teslim bekliyor", line)
        self.assertTrue(line.startswith("✓"))

    def test_open_question_has_no_pending_label(self):
        line = cs.question_head(_q("open", 0))
        self.assertNotIn("teslim bekliyor", line)
        self.assertTrue(line.startswith("?"))


if __name__ == "__main__":
    unittest.main()

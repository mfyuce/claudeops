"""STEWARD-DONE-CONFIRMED çelişki sorusuna sahip cevabı: yalnız net 'bitti' kapatır, çekinceli cevap kapatmaz (stdlib unittest)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402

NOW = 1_000_000.0


def q(answer, proj="p", at=NOW - 60):
    return sw.Question(id="q1", project=proj, text="STEWARD-DONE-CONFIRMED çelişti: 3 açık madde", created_at=at - 10,
                       status="answered", answer=answer, answered_at=at)


class DoneAnswerTest(unittest.TestCase):
    def ans(self, a, **kw):
        return sw.done_conflict_answer([q(a, **kw)], "p", NOW)

    def test_clear_yes_closes(self):
        for a in ("bitti", "Evet, bitti", "tamam kapat", "done", "yes finished"):
            self.assertIs(self.ans(a), True, a)

    def test_clear_no_does_not(self):
        for a in ("bitmedi", "hayır devam", "not done", "devam et"):
            self.assertIs(self.ans(a), False, a)

    def test_hedged_yes_does_not_close(self):
        for a in ("bitti ama X kaldı", "bitti, ancak testler eksik", "tamam fakat TBD#5 hariç", "done but Y remains",
                  "bitti sanırım?", "done except docs", "bitti, henüz push yok"):
            self.assertIs(self.ans(a), False, a)

    def test_no_answer_or_stale_or_other_project(self):
        self.assertIsNone(sw.done_conflict_answer([], "p", NOW))
        self.assertIsNone(self.ans("bitti", at=NOW - sw.DONE_ANSWER_TTL - 5))
        self.assertIsNone(self.ans("bitti", proj="baska"))


if __name__ == "__main__":
    unittest.main()

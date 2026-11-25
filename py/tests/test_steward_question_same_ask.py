"""Aynı soru açıkken yeniden açılmaz (25 Kas, iso canlı kopyaları): günlük paused süpürmesi ve yeniden yazılan STEWARD-ASK."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402

DAY = 24 * 3600
T0 = 1_800_000_000.0


class SameAskTest(_Tmp):
    def ask(self, project, text, at, **kw):
        with mock.patch.object(sw, "_now", return_value=at):
            return sw.add_question_ex(project, text, **kw)

    def opened(self):
        return [q for q in sw.load_questions() if q.status == "open"]

    def test_two_consecutive_sweeps_keep_one_open_question(self):
        projects = {"dalgicppr": sw.Project(name="dalgicppr", phase="paused")}
        cfg, st, n = sw.Config(), {}, {"v": 2}
        for day in range(4):
            now = T0 + day * (DAY + 60)
            n["v"] = 2 + day * 4
            acts, st = sw.plan_tick([], projects, st, cfg, now, [], [], open_work=lambda _p: n["v"], todo_sha=lambda _p: "h1")
            asks = [a for a in acts if a.kind == "ask_user"]
            self.assertEqual(len(asks), 1, day)
            _q, how = self.ask("dalgicppr", asks[0].payload["text"], now, options=asks[0].payload["options"])
            self.assertEqual(how, "new" if day == 0 else "merged")
        (q,) = self.opened()
        self.assertEqual(q.text, sw.paused_sweep_text("dalgicppr", 14))
        self.assertEqual(q.prev_texts, [])

    def test_answered_sweep_question_does_not_swallow_next_one(self):
        q, _ = self.ask("p", sw.paused_sweep_text("p", 1), T0)
        sw.answer_question(q.id, "Paused kalsın")
        q2, how = self.ask("p", sw.paused_sweep_text("p", 3), T0 + 10 * DAY)
        self.assertEqual(how, "new")
        self.assertNotEqual(q2.id, q.id)

    def test_same_question_sentence_with_different_lead_merges(self):
        a = "Yok; onay alındı. GPU0 boşalırsa kullanılsın mı? Şu an \"dokunma\" talimatı nedeniyle kullanmıyorum."
        b = "GPU0 boşalırsa kullanılsın mı? \"Dokunma\" talimatı geçerli olduğu için şu an kullanmıyorum."
        q, _ = self.ask("asp", a, T0)
        q2, how = self.ask("asp", b, T0 + 94)
        self.assertEqual((q2.id, how), (q.id, "merged"))
        (only,) = self.opened()
        self.assertEqual((only.text, only.prev_texts, only.extra_texts), (b, [a], []))

    def test_only_count_differs_merges_even_after_a_day(self):
        a = "Taslakta 3 açık madde kaldı, hakem turuna şimdi gireyim mi?"
        q, _ = self.ask("p", a, T0)
        q2, how = self.ask("p", a.replace("3 açık", "11 açık"), T0 + DAY + 3600)
        self.assertEqual((q2.id, how), (q.id, "merged"))
        self.assertEqual(len(self.opened()), 1)

    def test_identifier_numbers_and_generic_sentences_stay_separate(self):
        for i, (a, b) in enumerate((
                ("Taslağın bölüm 3 kısmı yazılsın mı?", "Taslağın bölüm 4 kısmı yazılsın mı?"),
                ("Parser düzeltmesi hazır. Commit ve push yapayım mı?",
                 "Makalenin kaynakçası güncellendi, yeni tablolar eklendi. Commit ve push yapayım mı?"))):
            p = f"p{i}"
            self.ask(p, a, T0)
            _q, how = self.ask(p, b, T0 + DAY + 3600)
            self.assertEqual(how, "new", b)

    def test_other_project_never_merges(self):
        self.ask("a", "GPU0 boşalırsa kullanılsın mı?", T0)
        _q, how = self.ask("b", "GPU0 boşalırsa kullanılsın mı?", T0 + 5)
        self.assertEqual(how, "new")


if __name__ == "__main__":
    unittest.main()

"""Devir mesajına oturumun/projenin AÇIK soruları eklenir (yeni oturum aynı soruyu yeniden açmasın)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402


class HandoverQuestionsTest(_Tmp):
    def test_note_lists_only_own_open_questions(self):
        a = sw.add_question("cli", "ncs koşu kayıtlarının yolu nerede olmalı bu proje için?", source="cli")
        sw.add_question("other", "başka projenin sorusu hakkında karar lazım mı değil mi?", source="other")
        b = sw.add_question("cli", "Evren günlük kota hatasında model listesi daraltılsın mı?", source="cli20261024")
        sw.answer_question(b.id, "evet")                 # cevaplanmış soru nota girmez
        note = sw.handover_questions_note(sw.load_questions(), "cli")
        self.assertIn(f"[{a.id}]", note)
        self.assertNotIn("başka projenin", note)
        self.assertNotIn(f"[{b.id}]", note)
        self.assertIn("Açık sorular", note)
        en = sw.handover_questions_note(sw.load_questions(), "cli", "en")
        self.assertIn("Open questions", en)
        self.assertEqual(sw.handover_questions_note(sw.load_questions(), "yok"), "")

    def test_note_is_bounded(self):
        qs = [sw.Question(id=f"q{i}", project="p", text="x" * 500, created_at=float(i), source="p") for i in range(12)]
        note = sw.handover_questions_note(qs, "p")
        self.assertEqual(note.count("\n- ["), sw.HANDOVER_QUESTIONS_MAX)
        self.assertIn("4 soru daha", note)
        self.assertLess(max(len(l) for l in note.split("\n")[1:-1]), sw.HANDOVER_QUESTION_CHARS + 20)

    def test_local_handover_passes_extra_only_when_open_questions(self):
        calls = []
        with mock.patch.object(web_steward, "_act", lambda n, *a, **k: calls.append((n, a, k)) or {"ok": True}):
            web_steward._local_handover("empty", "default", "tr")
            sw.add_question("empty", "bu açık soru devir mesajına girmeli mi girmemeli mi?", source="empty")
            web_steward._local_handover("empty", "default", "tr")
        self.assertEqual(calls[0][2], {"lang": "tr"})
        self.assertIn("Açık sorular", calls[1][2]["extra"])


if __name__ == "__main__":
    unittest.main()

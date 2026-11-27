"""TBD#377: değnekçi soru/fikir deposunda taşıma sırasında bulunan beş davranış (geçici dizin; stdlib unittest)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402


class OddSingleCharAnswerTest(_Tmp):
    """(1) `isdigit` doğru ama `int` kabul etmeyen ("²") ya da büyük hâli iki karakter olan ("ß") cevap istisna atıyordu."""

    CHARS = ("²", "①", "³", "ß", "ﬁ", "ŉ", "ǰ")

    def test_resolve_answer_keeps_free_text(self):
        q = sw.Question(id="q1", project="a", text="?", created_at=1.0, options=["bir", "iki", "üç"])
        for c in self.CHARS:
            with self.subTest(c):
                self.assertEqual(sw.resolve_answer(q, c), c)
        self.assertEqual(sw.resolve_answer(q, "²²"), "²²")

    def test_choices_unchanged(self):
        q = sw.Question(id="q1", project="a", text="?", created_at=1.0, options=["bir", "iki", "üç"])
        for raw, want in (("2", "iki"), ("b", "iki"), ("C", "üç"), ("İKİ", "İKİ"), ("ÜÇ", "üç"), ("٢", "iki"), ("4", "4")):
            with self.subTest(raw):
                self.assertEqual(sw.resolve_answer(q, raw), want)

    def test_answer_is_recorded(self):
        for c in ("²", "ß"):
            q = sw.add_question("a", f"hangi {c}?", options=["bir", "iki"])
            got = sw.answer_question(q.id, c)
            self.assertEqual((got.status, got.answer), ("answered", c))
            self.assertEqual(sw.find_question(q.id).answer, c)


class HeldAnswerRecordStandsAloneTest(_Tmp):
    """(2) `CEVAP OTURUM AÇMADI:` kaydı rutin işaretsiz gelse de başka soruya "ek" olmaz."""

    def test_not_appended_when_cap_is_full(self):
        texts = ["Kapak rengi ne olsun?", "Dergi hangisi seçilsin?", "Sunum tarihi ne zaman?"]
        self.assertEqual(len(texts), sw.MAX_OPEN_QUESTIONS_PER_PROJECT)
        for t in texts:
            sw.add_question("a", t)
        held = sw._HELD_ANSWER_PREFIX + " a projesi done/paused, sahibin cevabı (q9) oturum açmadı."
        q, how = sw.add_question_ex("a", held, source="motor")
        self.assertEqual((how, q.text), ("new", held))
        stored = sw.load_questions()
        self.assertEqual(len(stored), 4)
        self.assertFalse(any(x.extra_texts for x in stored))

    def test_ordinary_question_still_appended(self):
        for t in ("Kapak rengi ne olsun?", "Dergi hangisi seçilsin?", "Sunum tarihi ne zaman?"):
            sw.add_question("a", t)
        _, how = sw.add_question_ex("a", "Yazar sırası nasıl olacak?")
        self.assertEqual(how, "merged")


class MarkUnknownQuestionTest(_Tmp):
    """(3) soru bulunmazsa depo yeniden yazılmaz."""

    def test_no_write_when_missing(self):
        sw.add_question("a", "bir soru?")
        for fn in (sw.mark_notified, sw.mark_delivered):
            with self.subTest(fn.__name__), mock.patch.object(sw, "save_questions") as save:
                fn("q-yok")
                save.assert_not_called()

    def test_found_is_written(self):
        q = sw.add_question("a", "bir soru?")
        with mock.patch.object(sw, "_now", return_value=77.0):
            sw.mark_notified(q.id)
            sw.mark_delivered(q.id)
        got = sw.find_question(q.id)
        self.assertEqual((got.notified_at, got.delivered_at), (77.0, 77.0))


class UpsertTextTypeTest(_Tmp):
    """(4) metin alanlarında tip denetimi: `ValueError` (çağıranlar hata yanıtı verir), kayıt değişmez."""

    def test_non_string_is_refused_and_nothing_saved(self):
        sw.upsert_project("kitap", goal="amaç", model="m", effort="low", last_directive="d")
        before = sw.load_projects()["kitap"]
        for field in ("goal", "model", "effort", "last_directive"):
            for bad in (5, 1.5, True, ["x"], {"a": 1}):
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(ValueError) as cm:
                        sw.upsert_project("kitap", priority=1, **{field: bad})
                    self.assertIn(field, str(cm.exception))
                    self.assertEqual(sw.load_projects()["kitap"], before)

    def test_new_project_not_created(self):
        with self.assertRaises(ValueError):
            sw.upsert_project("yeni", goal=5)
        self.assertNotIn("yeni", sw.load_projects())

    def test_none_and_str_unchanged_and_notes_still_coerced(self):
        p = sw.upsert_project("kitap", goal="g", model=None, notes=5)
        self.assertEqual((p.goal, p.model, p.notes), ("g", "", "5"))

    def test_http_endpoint_reports_error(self):
        sw.upsert_project("kitap", goal="amaç")
        res = web_steward.http_project_upsert({"name": "kitap", "goal": 5})
        self.assertFalse(res["ok"])
        self.assertIn("goal", res["error"])
        self.assertEqual(sw.load_projects()["kitap"].goal, "amaç")


class AsciiDeferTest(unittest.TestCase):
    """(5) tam ASCII yazılan erteleme de ertelemedir."""

    def test_ascii_forms(self):
        for a in ("simdi verecegim", "Simdi verecegim.", "kararlari simdi verecegim", "kararlari sonra verecegim",
                  "  simdi   verecegim  ", "şimdi vereceğim", "simdi vereceğim"):
            with self.subTest(a):
                self.assertTrue(sw.is_defer_answer(a))

    def test_not_defer(self):
        for a in ("simdi verecegim: b", "verecegim", "simdi vermeyecegim", "evet"):
            with self.subTest(a):
                self.assertFalse(sw.is_defer_answer(a))


if __name__ == "__main__":
    unittest.main()

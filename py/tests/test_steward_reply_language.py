"""Sahip kuralı 21 Kas: proje oturumlarının STEWARD-* metni panel arayüz dilini izler. Direktif/açılış/devir 'Yanıt dili' satırı taşır,
yanlış dilde işaret metni için oturum başına günde BİR düzeltme notu. Canlı servis YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import handover as ho, steward as sw  # noqa: E402

DE = "Wir haben die Aufgabe nicht abgeschlossen und die Datei ist noch nicht fertig, aber der Plan ist gut"
EN = "Everything is done and the tests pass with the new config, which was the last item"
TR = "Her şey bitti ve testler geçti, sıradaki iş için karar gerekiyor"


class Heuristic(unittest.TestCase):
    def test_mismatch_both_ways(self):
        self.assertTrue(sw.text_lang_mismatch(DE, "tr"))
        self.assertTrue(sw.text_lang_mismatch(EN, "tr"))
        self.assertFalse(sw.text_lang_mismatch(TR, "tr"))
        self.assertTrue(sw.text_lang_mismatch(TR, "en"))
        self.assertTrue(sw.text_lang_mismatch(DE, "en"))
        self.assertFalse(sw.text_lang_mismatch(EN, "en"))

    def test_short_or_neutral_text_never_flagged(self):
        self.assertFalse(sw.text_lang_mismatch("yok", "tr"))
        self.assertFalse(sw.text_lang_mismatch("done", "tr"))
        self.assertFalse(sw.text_lang_mismatch("", "en"))
        self.assertFalse(sw.text_lang_mismatch("pytest tests/test_x.py -k foo passed 12 build ok", "tr"))      # kod/komut: dil işareti yok


class Directive(unittest.TestCase):
    def proj(self):
        return sw.Project(name="p", phase="planned")

    def test_language_line_in_full_and_compact_both_languages(self):
        for lang, want in (("tr", "Yanıt dili: Türkçe"), ("en", "Reply language: English")):
            self.assertIn(want, sw.build_directive(self.proj(), lang=lang))
            self.assertIn(want, sw.build_directive(self.proj(), lang=lang, compact=True, extra="x"))

    def test_handover_messages_carry_language(self):
        self.assertIn("Yanıt dili: Türkçe", ho.HANDOVER_MSG_DEFAULT)
        self.assertIn("Reply language: English", ho.HANDOVER_MSG_DEFAULT_EN)


class FixNote(unittest.TestCase):
    def test_once_per_day_per_session(self):
        cfg = sw.Config(lang="tr")
        st = {}
        a = sw.lang_fix_action("tunnel", "tunnel", DE, cfg, st, 1_000_000.0)
        self.assertIsNotNone(a)
        self.assertEqual(a.kind, "nudge")
        self.assertIn("Türkçe", a.payload["text"])
        self.assertIsNone(sw.lang_fix_action("tunnel", "tunnel", DE, cfg, st, 1_000_000.0 + 3600))           # günde bir
        self.assertIsNotNone(sw.lang_fix_action("tunnel", "tunnel", DE, cfg, st, 1_000_000.0 + 25 * 3600))
        self.assertIsNone(sw.lang_fix_action("other", "other", TR, cfg, {}, 1_000_000.0))                       # doğru dil: not yok

    def test_plan_tick_emits_note_for_wrong_language_marker(self):
        m = sw.scan_markers("bitti\nSTEWARD-NEXT: " + DE)
        self.assertIn(DE[:20], sw.marker_texts(m))
        m2 = sw.scan_markers("STEWARD-ASK: " + EN + "?")
        self.assertTrue(sw.text_lang_mismatch(sw.marker_texts(m2), "tr"))


if __name__ == "__main__":
    unittest.main()

"""Boştaki Claude oturumu: notta `sıradaki:` yoksa oturumun SON cevabında söylediği sıradaki iş dürtme metnine dayanak olur."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402


class StatedNextWorkTest(unittest.TestCase):
    def test_extracts_last_stated_next(self):
        self.assertEqual(sw.stated_next_work("X yaptım. Sonraki turda dizin betiğinden başlarım. Önce derlerim."),
                         "Sonraki turda dizin betiğinden başlarım.")
        self.assertIn("geçiyorum", sw.stated_next_work("Şimdi sunucu tarafı iki bulguya geçiyorum."))
        self.assertIn("e2e", sw.stated_next_work("Açık kalan teknik işler:\n- test\n- e2e testi"))

    def test_nothing_stated(self):
        self.assertEqual(sw.stated_next_work("Her şey bitti, commit edildi."), "")
        self.assertEqual(sw.stated_next_work(""), "")

    def test_explicit_next_line(self):
        t = "Rapor.\n\nProje bitmedi, bu yüzden `STEWARD-DONE` yazmıyorum.\n\nsıradaki: F5, başlık noktası düzeltmesi"
        self.assertEqual(sw.stated_next_work(t), "F5, başlık noktası düzeltmesi")
        self.assertEqual(sw.idle_finish_marker(t), ("", False))
        t2 = "-prv CLAUDE.md'deki READY FOR HANDOVER (2026-11-02) bölümü bayat.\n\nsıradaki: Sıra #3, ölçüm"
        self.assertEqual(sw.idle_finish_marker(t2), ("", False))

    def test_next_none_is_not_work(self):
        t = "Kalanlar TBD'de. STEWARD-DONE\n\nsıradaki: yok, kalanlar TBD'de"
        self.assertEqual(sw.stated_next_work(t), "")
        self.assertEqual(sw.idle_finish_marker(t)[0], sw.MARK_DONE)


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

"""`sıradaki:` notu TODO.md'de kapanmış maddeyi gösteriyorsa direktife/planlayıcıya girmez (25 Kas: 'TODO.md 632')."""
import unittest

from claudeops import steward as sw

NOTE = ("sıradaki: TODO.md 632 (roster'da olmayan projeye set -> her tick başarısız start, API'de reddet; "
        "history_size None handover sinyali); neden: STEWARD-NEXT sahipsiz iş")
CLOSED = ("- [x] (KAPANDI 22 Kas) **Küçükler:** roster'da olmayan projeye aktif faz `set` API'de de reddediliyor; "
          "`history_size` None için handover sinyali GEREKSİZ")
OPEN_OTHER = "- [ ] Panel kullanım sekmesinde İngilizce metinleri düzelt"


def _proj(notes):
    return sw.Project(name="p", notes=notes)


class StaleNoteTest(unittest.TestCase):
    def test_closed_item_is_stale(self):
        self.assertIn("roster", sw.stale_next_note(NOTE, CLOSED + "\n" + OPEN_OTHER))

    def test_open_item_wins(self):
        self.assertEqual(sw.stale_next_note(NOTE, CLOSED.replace("[x]", "[ ]")), "")
        self.assertEqual(sw.stale_next_note(NOTE, CLOSED + "\n" + CLOSED.replace("[x]", "[~]")), "")

    def test_unknown_is_not_stale(self):
        self.assertEqual(sw.stale_next_note(NOTE, ""), "")
        self.assertEqual(sw.stale_next_note(NOTE, OPEN_OTHER), "")
        self.assertEqual(sw.stale_next_note("sıradaki: roster set", CLOSED), "")
        self.assertEqual(sw.stale_next_note("serbest not", CLOSED), "")

    def test_copy_replaces_line_and_keeps_record(self):
        p = _proj(NOTE + "\nyalnız main checkout")
        for lang in ("tr", "en"):
            q = sw.without_stale_note(p, CLOSED, lang)
            self.assertEqual(sw.next_work_hint(q, None, real_only=True), "")
            self.assertEqual(sw.next_work_hint(q, lambda _n: 2), "TODO.md'deki ilk açık iş")
            self.assertIn("yalnız main checkout", q.notes)
            self.assertNotIn("sıradaki: TODO.md 632", sw.build_directive(q, lang=lang))
        self.assertEqual(p.notes, NOTE + "\nyalnız main checkout")
        self.assertIs(sw.without_stale_note(p, OPEN_OTHER), p)


if __name__ == "__main__":
    unittest.main()

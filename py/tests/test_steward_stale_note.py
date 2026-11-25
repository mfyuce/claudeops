"""`sıradaki:` notu TODO.md'de kapanmış maddeyi gösteriyorsa direktife/planlayıcıya girmez (25 Kas: 'TODO.md 632')."""
import os
import tempfile
import unittest
from unittest import mock

from claudeops import steward as sw
from claudeops.commands import web_steward as ws

NOTE = ("sıradaki: TODO.md 632 (roster'da olmayan projeye set -> her tick başarısız start, API'de reddet; "
        "history_size None handover sinyali); neden: STEWARD-NEXT sahipsiz iş")
CLOSED = ("- [x] (KAPANDI 22 Kas) **Küçükler:** roster'da olmayan projeye aktif faz `set` API'de de reddediliyor; "
          "`history_size` None için handover sinyali GEREKSİZ")
NOTE_WORDS = "sıradaki: roster'da olmayan projeye aktif faz set API'de reddet, history_size handover sinyali"
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

    def test_item_moved_to_done_is_stale(self):
        for done in (CLOSED, CLOSED.replace("- [x] ", "- ")):      # DONE.md satırı kutusuz da kapalıdır
            self.assertIn("roster", sw.stale_next_note(NOTE_WORDS, OPEN_OTHER, done), done)
            self.assertIsNot(sw.without_stale_note(_proj(NOTE_WORDS), OPEN_OTHER, done_text=done), None)

    def test_open_item_wins_over_done(self):
        self.assertEqual(sw.stale_next_note(NOTE_WORDS, CLOSED.replace("[x]", "[ ]"), CLOSED), "")
        self.assertEqual(sw.stale_next_note(NOTE_WORDS, "", CLOSED.replace("[x]", "[ ]")), "")

    def test_done_history_needs_stronger_match(self):
        """DONE.md geçmiş özetidir: aynı konunun ÖNCEKİ aşaması (kısmi örtüşme) yeni işi bayat saydırmaz."""
        note = "sıradaki: kullanım sekmesi uzak makine seçici ikinci aşama toplam grafiği"
        done = "- 25 Kas: kullanım sekmesi uzak makine seçici ilk aşama eklendi"      # 6/9 sözcük
        self.assertEqual(sw.stale_next_note(note, OPEN_OTHER, done), "")
        self.assertNotEqual(sw.stale_next_note(note, done.replace("- ", "- [x] ")), "")      # TODO'daki kapalı maddede eşik aynı


class DoneFileWiringTest(unittest.TestCase):
    def test_note_project_reads_done_md(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in (("TODO.md", OPEN_OTHER), ("DONE.md", CLOSED.replace("- [x] ", "- "))):
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write(text + "\n")
            p = _proj(NOTE_WORDS)
            with mock.patch.object(ws, "_cwd_resolver", lambda: (lambda _n: d)):
                q = ws._fresh_note_project({"p": p}, p, "tr")
                found = ws._claim_check_of({"p": p})("p")
            self.assertNotIn("sıradaki:", q.notes)
            self.assertIn("KAPALI", q.notes)
            self.assertTrue(any("roster" in x for x in found), found)


if __name__ == "__main__":
    unittest.main()

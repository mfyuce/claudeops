"""claude_idle dürtmesi 'iş VAR MI'ya dayanır (metin ayrıştırmasına değil): sabit mesaj, `sıradaki: yok` durdurur;
`STEWARD-NEXT` yalnız bilgi; idle_finish_marker olumsuz kalıplara karşı."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from test_steward_ucli_idle import NOW, cview, cplan, proj  # noqa: E402


class WorkBasedNudgeTest(unittest.TestCase):
    def test_open_ownerless_todo_nudges_with_fixed_text(self):
        acts, st = cplan([cview()], proj(""), open_work=lambda n: 4)
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])
        self.assertEqual(acts[0].payload["text"], sw.CLAUDE_IDLE_NUDGE_TEXT)
        self.assertIn("sıradaki: yok", acts[0].payload["text"])
        self.assertIn("4", acts[0].payload["next"])

    def test_no_open_work_no_nudge(self):
        self.assertEqual(cplan([cview()], proj(""), open_work=lambda n: 0)[0], [])
        self.assertEqual(cplan([cview()], proj(""), open_work=lambda n: None)[0], [])

    def test_text_content_does_not_matter(self):
        # son cevapta hiçbir 'sıradaki' ifadesi yok: yine de iş varsa dürtülür
        acts, _ = cplan([cview(last_assistant="Tamamlandı, testler yeşil.")], proj(""), open_work=lambda n: 2)
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])

    def test_next_none_stops_until_todo_changes(self):
        v = cview(last_assistant="Hepsi bitti.\nsıradaki: yok")
        acts, st = cplan([v], proj(""), open_work=lambda n: 3)
        self.assertEqual(acts, [])
        self.assertEqual(st["next_none"]["cli"]["open"], 3)
        acts, st2 = cplan([v], proj(""), state=st, open_work=lambda n: 3)      # TODO aynı: durur
        self.assertEqual(acts, [])
        acts, st3 = cplan([v], proj(""), state=st, open_work=lambda n: 5)      # TODO değişti: yeniden dürtülür
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])

    def test_steward_next_none_marker_also_stops_and_new_activity_resumes(self):
        v = cview(last_assistant="bitti\nSTEWARD-NEXT: yok")
        _, st = cplan([v], proj(""), open_work=lambda n: 3)
        self.assertIn("cli", st["next_none"])
        v2 = cview(last_assistant="yeni iş yaptım")
        acts, st2 = cplan([v2], proj(""), state=st, open_work=lambda n: 3)
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])
        self.assertNotIn("cli", st2.get("next_none", {}))

    def test_max_consecutive_kept(self):
        st, n = {}, 0
        for i in range(5):
            acts, st = cplan([cview(idle=3100)], proj(""), state=st, now=NOW + 3100 * i, open_work=lambda n_: 3)
            n += len(acts)
        self.assertEqual(n, 2)

    def test_owner_wait_and_gate_still_skip(self):
        self.assertEqual(cplan([cview(last_assistant="sahipte, bekliyorum")], proj(""), open_work=lambda n: 3)[0], [])


class StewardNextMarkerTest(unittest.TestCase):
    def test_scan_next_marker_last_wins_and_ignores_fenced_and_prose(self):
        m = sw.scan_markers("a\nSTEWARD-NEXT: birinci\n```\nSTEWARD-NEXT: kod\n```\n> STEWARD-NEXT: alıntı\nSTEWARD-NEXT: ikinci")
        self.assertEqual(m["next"], "ikinci")
        self.assertEqual(sw.scan_markers("bunu `STEWARD-NEXT: x` diye yaz")["next"], None)
        self.assertEqual(sw.scan_markers("cevabın sonunda STEWARD-NEXT: x yaz")["next"], None)
        self.assertEqual(sw.scan_markers("STEWARD-NEXT: <iş>")["next"], None)

    def test_next_creates_no_question_or_decision(self):
        m = sw.scan_markers("STEWARD-NEXT: testleri yaz")
        self.assertEqual(sw.marker_record_actions("cli", "cli", m), [])

    def test_note_project_next_state(self):
        st = {}
        sw.note_project_next(st, "p", "s1", sw.scan_markers("STEWARD-NEXT: x işi"), NOW)
        self.assertEqual(st["project_next"]["p"]["text"], "x işi")
        self.assertFalse(st["project_next"]["p"]["none"])
        sw.note_project_next(st, "p", "s1", sw.scan_markers("STEWARD-NEXT: yok"), NOW + 1)
        self.assertTrue(st["project_next"]["p"]["none"])

    def test_plan_markers_records_state(self):
        v = cview(last_assistant="bitti\nSTEWARD-NEXT: raporu yaz")
        projects = proj("")
        _, st = sw.plan_markers([v], projects, {}, sw.Config(enabled=True))
        self.assertEqual(st["project_next"]["cli"]["text"], "raporu yaz")

    def test_explain_shows_next_work_and_next_none(self):
        projects = proj("")
        v = cview(last_assistant="STEWARD-NEXT: yok")
        c = sw.Config(enabled=True, mode="act", claude_idle="act")
        state = {"project_next": {"cli": {"text": "yok", "none": True, "at": NOW, "session": "cli"}},
                 "next_none": {"cli": {"open": 3, "at": NOW, "session": "cli"}}}
        why = sw.explain_idle_all([v], projects, state, c, NOW, [], open_work=lambda n: 3)
        self.assertEqual(why["cli"]["code"], "next_none")
        self.assertTrue(why["cli"]["next_work"]["none"])

    def test_protocol_mentions_marker(self):
        self.assertIn("STEWARD-NEXT:", sw._PROTOCOL_TR)
        self.assertIn("STEWARD-NEXT:", sw._PROTOCOL_EN)


class FinishMarkerNegationTest(unittest.TestCase):
    def test_negative_phrasings_are_not_finished(self):
        for t in ("STEWARD-DONE yazmıyorum, iş kaldı", "STEWARD-DONE vermiyorum", "şimdilik STEWARD-DONE yazmıyorum",
                  "yapacak iş yok demiyorum, sürüyor", "yapacak iş yok değil", "```\nSTEWARD-DONE\n```", "> STEWARD-DONE",
                  "NO-STEWARD-DONE"):
            self.assertEqual(sw.idle_finish_marker(t), ("", False), t)

    def test_real_finish_still_detected(self):
        self.assertEqual(sw.idle_finish_marker("STEWARD-DONE")[0], "STEWARD-DONE")
        self.assertEqual(sw.idle_finish_marker("işler bitti STEWARD-DONE")[0], "STEWARD-DONE")
        self.assertEqual(sw.idle_finish_marker("Şu an yapacak iş yok.")[0], "yapacak iş yok")


if __name__ == "__main__":
    unittest.main()

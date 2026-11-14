"""STEWARD-JOB kapısı (yalnız kayıtlı servise gerçek iş isteği) + proje başına açık soru sınırı (L7b). Ağ/tmux YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class Verdict(unittest.TestCase):
    KINDS = {"varaka-import", "embed"}

    def v(self, body, kinds=KINDS, reg=True):
        return sw.job_marker_verdict(body, kinds, reg)

    def test_real_request(self):
        self.assertEqual(self.v("varaka-import data/x.json yeni set"), (True, ""))
        self.assertEqual(self.v("embed `a.json`"), (True, ""))

    def test_status_notes(self):
        for b in ("Retention kodlaması (`feat/x`) sürüyor; bitince commit listesiyle döneceğim.",
                  "Retention ajanı çalışıyor; arkasından sıkıştırma gelecek.",
                  "embed a.json sürüyor, bitince döneceğim"):
            self.assertEqual(self.v(b), (False, "status_note"), b)

    def test_unknown_kind_and_no_service(self):
        self.assertEqual(self.v("regress x.json"), (False, "unknown_kind"))
        self.assertEqual(self.v("embed x", reg=False), (False, "no_service"))

    def test_catalog_unreachable_skips_kind_check_only(self):
        self.assertEqual(self.v("regress x.json", kinds=None), (True, ""))
        self.assertEqual(self.v("Retention sürüyor", kinds=None), (False, "status_note"))


class Cap(_Tmp):
    def test_open_question_cap_appends_extra(self):
        ids = []
        for i in range(3):
            q, how = sw.add_question_ex("anomaly", f"tamamen farkli konu numara {i} kutu{i} yelpaze{i}", source="s", paths=None)
            self.assertEqual(how, "new")
            ids.append(q.id)
        q4, how4 = sw.add_question_ex("anomaly", "bambaska dorduncu mevzu zeytin nehir", source="s2", paths=None)
        self.assertEqual(how4, "merged")
        self.assertIn(q4.id, ids)
        qs = [q for q in sw.load_questions(None) if q.project == "anomaly"]
        self.assertEqual(len(qs), 3)
        tgt = next(q for q in qs if q.id == q4.id)
        self.assertEqual(tgt.extra_texts, ["bambaska dorduncu mevzu zeytin nehir"])
        self.assertEqual(tgt.asked_again, 1)

    def test_other_project_job_and_routine_unaffected(self):
        for i in range(3):
            sw.add_question_ex("anomaly", f"konu {i} kutu{i} yelpaze{i} ormanlik{i}", paths=None)
        self.assertEqual(sw.add_question_ex("baska", "ilgisiz soru", paths=None)[1], "new")
        self.assertEqual(sw.add_question_ex("anomaly", "rutin soru zeytin?", routine=True, paths=None)[1], "new")
        self.assertEqual(sw.add_question_ex("anomaly", sw.JOB_REQUEST_PREFIX + "embed a.json", routine=True, paths=None)[1], "new")

    def test_answered_frees_slot(self):
        qs = [sw.add_question_ex("anomaly", f"konu {i} kutu{i} yelpaze{i} ormanlik{i}", paths=None)[0] for i in range(3)]
        sw.answer_question(qs[0].id, "tamam", paths=None)
        self.assertEqual(sw.add_question_ex("anomaly", "yeni bambaska mevzu limon", paths=None)[1], "new")


class Gate(_Tmp):
    def _action(self, text):
        return sw.Action("ask_user", "anomaly20261101", "STEWARD-JOB", {"project": "anomaly", "text": sw.JOB_REQUEST_PREFIX + text, "routine": True})

    def test_rejected_without_service_no_question(self):
        orig_run, orig_tm = ws._running, ws.is_tmux_backed
        ws._running = lambda n: None
        try:
            r = ws._job_marker_gate(self._action("Retention sürüyor, bitince döneceğim"), sw.Config(), "anomaly20261101", "", None)
        finally:
            ws._running, ws.is_tmux_backed = orig_run, orig_tm
        self.assertEqual(r["skipped"], "job_marker_no_service")
        self.assertEqual(sw.load_questions(None), [])


if __name__ == "__main__":
    unittest.main()


class KindsCatalogue(unittest.TestCase):
    from claudeops import steward_jobs as sj
    ROWS = [{"name": "import_pdf", "writes": True, "params": {"kaynak": "x", "limits": {"value_max_chars": 200}}},
            {"name": "embed", "writes": True, "params": {"eser_list": "y"}},
            {"name": "noop", "writes": False, "params": {}}, {"name": "pdf_text", "writes": False, "params": {}}]

    def test_parse_both_shapes(self):
        sj = self.sj
        self.assertEqual([r["name"] for r in sj.parse_kinds({"kinds": self.ROWS})], ["import_pdf", "embed", "noop", "pdf_text"])
        self.assertEqual([r["name"] for r in sj.parse_kinds({"a": {}, "b": {}})], ["a", "b"])
        self.assertEqual([r["name"] for r in sj.parse_kinds(["x", {"kind": "y"}])], ["x", "y"])

    def test_closest_three(self):
        sj = self.sj
        self.assertEqual(sj.closest_kinds("varaka-import", [r["name"] for r in self.ROWS])[0], "import_pdf")
        self.assertEqual(len(sj.closest_kinds("zzz", [r["name"] for r in self.ROWS])), 3)
        self.assertEqual(sj.closest_kinds("pdf", [r["name"] for r in self.ROWS])[:2], ["import_pdf", "pdf_text"])

    def test_format(self):
        sj = self.sj
        tab = sj.format_kinds("varaka", self.ROWS)
        self.assertIn("import_pdf", tab)
        self.assertIn("en çok 50 dosya", tab)
        det = sj.format_kinds("varaka", self.ROWS, "import_pdf")
        self.assertIn("param kaynak", det)
        self.assertIn("limit value_max_chars: 200", det)
        self.assertIn("en yakın", sj.format_kinds("varaka", self.ROWS, "embd"))

    def test_prompts_mention_catalogue(self):
        for txt in (sw.MODEL_RULE_TR, sw.MODEL_RULE_EN):
            self.assertIn("steward jobs kinds", txt)
            self.assertIn("steward_jobs kinds=true", txt)
        self.assertIn("jobs kinds", self.sj.KINDS_HINT)


class TourLoopSig(unittest.TestCase):
    def _run(self, items_for):
        v = [sw.SessionView(name="degnekci_iso", running=True, cwd="/w", cli="claude", last_assistant="tamam")]
        st = {}
        broke = 0
        for i in range(12):
            acts = [sw.Action("tour", "degnekci_iso", "1 madde", {"items": items_for(i)})]
            out, st = sw.loop_guard(acts, v, st, 1000.0 + i)
            broke += sum(1 for a in out if a.kind == "loop_break")
        return broke

    def test_changing_items_do_not_trip(self):
        self.assertEqual(self._run(lambda i: [{"kind": "routine", "id": f"q{i}", "name": "p"}]), 0)

    def test_same_items_same_reply_trip(self):
        self.assertEqual(self._run(lambda i: [{"kind": "routine", "id": "q1", "name": "p"}]), 1)


class GateMessage(_Tmp):
    def test_note_has_catalogue_hint_file_rule_and_closest_kinds(self):
        sent = []

        class S:
            pid, name, cli = 1, "anomaly20261101", "claude"
        saved = (ws._registered_job_kinds, ws._running, ws.is_tmux_backed, ws._box_has_typed_input, ws._send)
        ws._registered_job_kinds = lambda now: (True, {"import_pdf", "embed", "noop", "pdf_text"})
        ws._running, ws.is_tmux_backed = (lambda n: S()), (lambda pid: True)
        ws._box_has_typed_input = lambda n, cli="": False
        ws._send = lambda n, c, t: sent.append(t) or True
        ws._JOB_NOTE_SENT.clear()
        try:
            a = sw.Action("ask_user", "anomaly20261101", "STEWARD-JOB",
                          {"project": "anomaly", "text": sw.JOB_REQUEST_PREFIX + "varaka-import a.pdf", "routine": True})
            r = ws._job_marker_gate(a, sw.Config(), "anomaly20261101", "", None)
            r2 = ws._job_marker_gate(a, sw.Config(), "anomaly20261101", "", None)
        finally:
            ws._registered_job_kinds, ws._running, ws.is_tmux_backed, ws._box_has_typed_input, ws._send = saved
            ws._JOB_NOTE_SENT.clear()
        self.assertEqual(r["skipped"], "job_marker_unknown_kind")
        self.assertEqual(len(sent), 1)                       # oturuma BİR kez
        self.assertFalse(r2["noted"])
        for frag in ("yalnız paylaşımlı servise", "py/cops steward jobs kinds", "proje dizini İÇİNDE", "en çok 50 dosya", "en yakın 3", "import_pdf"):
            self.assertIn(frag, sent[0])
        self.assertEqual(sw.load_questions(None), [])

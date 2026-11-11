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

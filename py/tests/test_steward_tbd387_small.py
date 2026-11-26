"""TBD#387 (2-6): "sıradaki:" okuyucuları, İngilizce panel yazımları, döngü duraklaması saati, ASK kapısı özeti."""
import argparse
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import steward as cli, web_steward as ws  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402

NO_WORK = ("-", "—", "–", "- .", "`-`", "n/a", "N/A.", "n/a (sahipte)", "bitti", "Bitti.", "**bitti**", "bitti (devir yazıldı)",
           "bitti, kalanlar TBD'de", "bitti - sahipte", "done", "done.", "BİTTİ")
REAL_WORK = ("- testleri koş", "- [ ] testleri koş", "bitti mi diye kontrol et", "done.md dosyasını düzenle",
             "done listesini taşı", "n/a değerlerini ayıkla", "bitti_listesi.py yaz", "F5 düzeltmesi")


def _view(name, **kw):
    base = dict(running=True, cwd="/tmp/x", cli="claude", busy=False, history_size=100, tmux=True,
                started_at=1000.0, last_activity=1000.0)
    base.update(kw)
    return sw.SessionView(name=name, **base)


class NoWorkValuesTest(unittest.TestCase):
    def test_next_line(self):
        for v in NO_WORK:
            with self.subTest(v):
                self.assertEqual(sw.next_line(f"Rapor.\nsıradaki: {v}"), (True, ""))
                self.assertEqual(sw.stated_next_work(f"Rapor.\nsıradaki: {v}"), "")

    def test_finish_marker_not_hidden(self):
        for v in NO_WORK:
            with self.subTest(v):
                self.assertEqual(sw.idle_finish_marker(f"STEWARD-DONE\n\nsıradaki: {v}")[0], sw.MARK_DONE)

    def test_real_work_stays(self):
        for v in REAL_WORK:
            with self.subTest(v):
                has, what = sw.next_line(f"sıradaki: {v}")
                self.assertTrue(has and what, what)

    def test_note_hint_and_marker(self):
        for v in NO_WORK:
            with self.subTest(v):
                proj = sw.Project(name="p", notes=f"sıradaki: {v}")
                self.assertEqual(sw.next_work_hint(proj, lambda _n: 3), "")
                self.assertEqual(sw.marker_next_work(f"STEWARD-NEXT: {v}"), "")
                self.assertTrue(sw.next_none_stated(f"STEWARD-NEXT: {v}"))
                st = {}
                sw.note_project_next(st, "p", "p1", sw.scan_markers(f"STEWARD-NEXT: {v}"), 5.0)
                self.assertTrue(st["project_next"]["p"]["none"])
        for v in ("- testleri koş", "bitti mi diye kontrol et", "F5 düzeltmesi"):
            with self.subTest(v):
                self.assertTrue(sw.next_work_hint(sw.Project(name="p", notes=f"sıradaki: {v}"), real_only=True))
                self.assertTrue(sw.marker_next_work(f"STEWARD-NEXT: {v}"))


class EmptyNextLineTest(unittest.TestCase):
    def test_next_line_is_not_taken_as_work(self):
        for t in ("sıradaki:\nBugün hava güzel.", "sıradaki:   \n\nRapor yazıldı.", "next:\r\nSome report.",
                  "**sıradaki:**\n- F5 düzeltmesi", "sıradaki\t:\n- a", "sıradaki:\u2028başka satır", "sıradaki:"):
            with self.subTest(t):
                self.assertEqual(sw.next_line(t), (True, ""))
                self.assertEqual(sw.stated_next_work(t), "")

    def test_last_line_wins_even_when_empty(self):
        self.assertEqual(sw.next_line("sıradaki: eski iş\nara\nsıradaki:"), (True, ""))

    def test_same_line_still_read(self):
        self.assertEqual(sw.next_line("x\r\nsıradaki:\tF5\r\ny"), (True, "F5"))
        self.assertEqual(sw.next_line("**sıradaki:** F5"), (True, "** F5"))

    def test_block_form_does_not_count_as_finished(self):
        # boş satırın ardında metin var: belirsiz, oturum bitti sayılıp kapatılmaz (eski davranış)
        for t in ("STEWARD-DONE\nsıradaki:\n- F5", "READY FOR HANDOVER\nsıradaki:\n- F5", "sıradaki:\n\nSTEWARD-DONE"):
            with self.subTest(t):
                self.assertEqual(sw.idle_finish_marker(t), ("", False))
        self.assertEqual(sw.idle_finish_marker("STEWARD-DONE\nsıradaki:\n  ")[0], sw.MARK_DONE)


class EnglishPanelTest(unittest.TestCase):
    def test_idle_wait_detail(self):
        proj = sw.Project(name="p", cadence_minutes=0)
        v = _view("p", blueprint="p", last_activity=1000.0)
        for lang, want in (("en", "40 min"), ("tr", "40 dk")):
            cfg = sw.Config(enabled=True, lang=lang, claude_idle="act", claude_idle_nudge_secs=3000)
            got = sw.explain_idle(proj, [v], {"p": proj}, {}, cfg, 1600.0, [])
            self.assertEqual((got["code"], got["detail"]), ("idle_wait", want))

    def test_skip_ratio(self):
        day = "2026-11-26"
        entries = [{"ts": f"{day}T10:00:00", "event": e} for e in ("tour", "tour", "tour", "tour", "skip", "skip", "skip")]
        self.assertIn("3 skips (75%)", sw.daily_summary(entries, day, "en"))
        self.assertIn("3 skip (%75)", sw.daily_summary(entries, day, "tr"))

    REP = {"keepwarm": {"count": 2, "names": {"a": 2}, "chars": 10, "first": 1.0, "last": 2.0}}

    def test_dry_report_text(self):
        en = sw.dry_report_text(self.REP, 72, "en")
        self.assertEqual(en, "Measurement (dry) modes, last 72 hours:\n- would:keepwarm [keepwarm]: 2 events, ~10 characters (a×2)\n")
        self.assertEqual(sw.dry_report_text({}, 5, "en"), "No `would:*` events in the last 5 hours.\n")
        self.assertEqual(sw.dry_report_text({}, 5), "Son 5 saatte `would:*` olayı yok.\n")
        self.assertIn("2 olay, ~10 karakter", sw.dry_report_text(self.REP, 72, "tr"))

    def test_cli_follows_panel_language(self):
        with mock.patch.object(sw, "dry_report", return_value={}), \
                mock.patch.object(cli, "steward_config", return_value=sw.Config(lang="en")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.cmd_dry_report(argparse.Namespace(sid="default", steward="default", hours=72))
        self.assertEqual(out.getvalue(), "No `would:*` events in the last 72 hours.\n")

class DryQuestionLanguageTest(_Tmp):
    def test_dry_question_follows_panel_language(self):
        seen = {}

        def add(project, text, **kw):
            seen.update(text=text, options=kw.get("options"))
            return sw.Question(id="q1", project=project, text=text, created_at=1.0), "same"

        rep = {"keepwarm": dict(EnglishPanelTest.REP["keepwarm"])}
        with mock.patch.object(sw, "dry_report", return_value=rep), mock.patch.object(sw, "add_question_ex", side_effect=add):
            self.assertEqual(ws.maybe_dry_ask(sw.Config(lang="en", keepwarm="dry"), 10 * 86400.0), "q1")
        self.assertIn("Measurement (dry) modes", seen["text"])
        for turkish in ("Ölçüm", "saat", "Rapor:", "kalsın"):
            self.assertNotIn(turkish, seen["text"] + " ".join(seen["options"]))


class LoopPauseHoursTest(unittest.TestCase):
    def test_short_pauses_never_report_zero_hours(self):
        for kind, hours, minutes in (("tour", 1, 45), ("deliver_answer", 1, 15), ("nudge", 6, 360)):
            with self.subTest(kind):
                st, out = {}, []
                for i in range(sw.LOOP_MAX + 1):
                    out, st = sw.loop_guard([sw.Action(kind, "p", "x", {})], [], st, 1000.0 + i)
                self.assertEqual((out[0].payload["pause_h"], out[0].payload["pause_min"]), (hours, minutes))


class AskGateSummaryTest(unittest.TestCase):
    def test_applied_shadow_record_counted_once(self):
        ev = [{"id": "q1", "project": "p", "question": "s", "answer": "c", "applied": True, "mode": "shadow", "allow": True},
              {"id": "q2", "applied": False, "mode": "shadow", "allow": True}]
        lines = sw._ask_gate_lines(ev, {}, True)
        self.assertEqual(lines[0], "- ASK gate: brain answered for the owner 1, refused 0, shadow 1 (1 would pass)")
        self.assertEqual(len(lines), 2)          # yazılan cevap sahibe yine listelenir


if __name__ == "__main__":
    unittest.main()

"""Sentetik uçtan uca: ucli-lessons köprüsü (reviewer `_write_lesson` -> tick -> projenin oturumuna direktif) ve devir mesajındaki
açık sorular (`add_question` -> `http_handover` -> devir geri çağrısına `extra`). Canlı Evren/Anthropic/oturum YOK."""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_steward_engine_multi import _Engine, _view  # noqa: E402
from claudeops import review as rv, settings, steward as sw, steward_lessons as sl  # noqa: E402
from claudeops.commands import web_review as wr, web_steward as ws  # noqa: E402

EV = rv.ReviewTarget("evren", "deepseek-v4.1-flash", "deepseek-v4.1-flash")


class LessonsBridge(_Engine):
    def setUp(self):
        super().setUp()
        settings.save_settings({
            "steward": {"enabled": "on", "mode": "act", "card_refresh": "off"},
            "stewards": {"rvw": {"enabled": "on", "mode": "act", "role": "reviewer"}}})
        self.given = []
        for p in (mock.patch.object(ws, "_give_directive", self._give),
                  mock.patch.object(ws, "_project_cwd", lambda name: self.dir.name)):
            p.start()
            self.addCleanup(p.stop)
        sw.upsert_project("cli", phase="planned", cadence_minutes=0)
        self.rv_paths = sw.paths_for("rvw")
        os.makedirs(self.rv_paths.root, exist_ok=True)

    def _give(self, project, text, **kw):
        self.given.append((project.name, text, kw))
        return {"ok": True, "name": kw.get("session_name") or project.name}

    def lesson(self, project="ncs", err="zaman aşımı"):
        wr._write_lesson(self.rv_paths, project, EV, "error", err)

    def view(self, **kw):
        return _view("cli", last_activity=time.time(), **kw)

    def test_reviewer_lesson_reaches_cli_session_once(self):
        self.lesson("ncs", "timeout 20 dk")
        self.views = [self.view()]
        res = ws.tick_once("manual", "default")
        self.assertIn("deliver_lesson", [a["kind"] for a in res["actions"]])
        name, text, kw = self.given[0]
        self.assertEqual(name, "cli")
        self.assertIn("proje=ncs model=deepseek-v4.1-flash", text)
        self.assertFalse(kw["start_if_stopped"])
        ws.tick_once("manual", "default")
        self.assertEqual(len(self.given), 1)                                    # aynı ders iki kez gitmez
        self.assertIn("lesson_delivered", [e["event"] for e in sw.tail_log(50)])
        self.lesson("zlkrn", "boş cevap")                                        # yeni satır ayrıca gider
        ws.tick_once("manual", "default")
        self.assertEqual(len(self.given), 2)
        self.assertIn("proje=zlkrn", self.given[1][1])
        self.assertNotIn("proje=ncs", self.given[1][1])

    def test_lesson_masks_learned_password_in_error(self):
        wr._write_lesson(self.rv_paths, "ncs", EV, "error", "bağlantı s3cr3tPW ile reddedildi", ["s3cr3tPW"])
        with open(os.path.join(self.rv_paths.root, sl.LESSONS_FILE), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("s3cr3tPW", text)
        self.assertIn("[REDACTED]", text)

    def test_lesson_already_sent_in_state_is_not_resent(self):
        """Eylem planlandıktan sonra aynı ders başka yoldan `lessons_sent`e yazıldıysa tekrar gönderilmez."""
        self.lesson("ncs", "timeout 20 dk")
        lessons = sl.read_lessons([self.rv_paths.root])
        hashes = [h for h, _ in lessons]
        sl.mark_sent(hashes, sw.paths_for("default"))
        action = sw.Action("deliver_lesson", "cli", "lesson",
                           {"project": "ncs", "hashes": hashes, "lines": [ln for _, ln in lessons]})
        cfg = ws.steward_config("default")
        res = ws._deliver_lesson(action, cfg, {"ncs": sw.Project(name="ncs")})
        self.assertEqual(res.get("skipped"), "already sent")
        self.assertEqual(self.given, [])

    def test_waits_for_idle_session_and_never_starts_one(self):
        self.lesson()
        for v in ([self.view(busy=True)], [self.view(subagent_active=True)], [self.view(running=False)], []):
            self.views = v
            ws.tick_once("manual", "default")
        self.assertEqual((self.given, self.touched), ([], []))
        self.views = [self.view()]
        ws.tick_once("manual", "default")
        self.assertEqual(len(self.given), 1)

    def test_observe_mode_only_logs_would_and_disabled_project_sends_nothing(self):
        settings.save_settings({"steward": {"enabled": "on", "mode": "observe", "card_refresh": "off"},
                                "stewards": {"rvw": {"enabled": "on", "mode": "act", "role": "reviewer"}}})
        self.lesson()
        self.views = [self.view()]
        res = ws.tick_once("manual", "default")
        self.assertEqual([d["kind"] for d in res["dry"]], ["deliver_lesson"])
        self.assertEqual(self.given, [])
        settings.save_settings({"steward": {"enabled": "on", "mode": "act", "card_refresh": "off", "lessons_project": "off"},
                                "stewards": {"rvw": {"enabled": "on", "mode": "act", "role": "reviewer"}}})
        ws.tick_once("manual", "default")
        self.assertEqual(self.given, [])

    def test_hand_written_and_old_lines_are_not_delivered(self):
        with open(os.path.join(self.rv_paths.root, sl.LESSONS_FILE), "w") as f:
            f.write("- 2026-10-24 elle yazılmış not\n- 2026-10-24 02:14 proje=copsdev eski etiketsiz satır\n")
        self.views = [self.view()]
        ws.tick_once("manual", "default")
        self.assertEqual(self.given, [])


class HandoverQuestions(_Engine):
    def test_open_question_travels_in_handover_extra(self):
        captured = []

        def handover(name, lang="tr", exact=False, extra=""):
            captured.append((name, extra))
            return {"ok": True}
        ws.configure(status_payload=lambda: {"sessions": []}, fleet_status=lambda: {},
                     start=lambda *a, **k: {"ok": True}, stop=lambda *a, **k: {"ok": True}, handover=handover,
                     register_project=lambda *a, **k: {"ok": True})
        sw.upsert_project("cli", phase="planned", cadence_minutes=0)
        self.settings()
        patcher = mock.patch.object(ws, "find_sessions", lambda **k: [])      # makinedeki gerçek `cli*` oturumu çözülmesin
        patcher.start()
        self.addCleanup(patcher.stop)
        res = ws.http_handover({"name": "cli", "actor": "human"}, "default")
        self.assertTrue(res["ok"], res)
        self.assertEqual(captured[0], ("cli", ""))                                # açık soru yok: mesaj eskisi gibi
        q = sw.add_question("cli", "ncs koşu kayıtlarının yolu hangi dizinde tutulmalı sizce?", source="cli")
        ws.http_handover({"name": "cli", "actor": "human"}, "default")
        self.assertIn(f"[{q.id}]", captured[1][1])
        sw.answer_question(q.id, "reviews/ncs")
        ws.http_handover({"name": "cli", "actor": "human"}, "default")
        self.assertEqual(captured[2][1], "")                                      # cevaplanınca notta yok

    def test_project_name_resolves_to_the_dated_session(self):
        """`cli` projesi, canlı oturum `cli20261023`: devir/durdurma/skip durumu ve açık sorular GERÇEK oturum adıyla çalışır."""
        import types
        captured, stopped = [], []

        def handover(name, lang="tr", exact=False, extra=""):
            captured.append((name, extra))
            return {"ok": True}
        ws.configure(status_payload=lambda: {"sessions": []}, fleet_status=lambda: {},
                     start=lambda *a, **k: {"ok": True}, stop=lambda name, **k: stopped.append(name) or {"ok": True},
                     handover=handover, register_project=lambda *a, **k: {"ok": True})
        sw.upsert_project("cli", phase="planned", cadence_minutes=0)
        self.settings()
        q = sw.add_question("cli", "ncs koşu kayıtlarının yolu hangi dizinde tutulmalı sizce?")   # source yok: proje adıyla eşleşir
        with mock.patch.object(ws, "find_sessions", lambda **k: [types.SimpleNamespace(name="cli20261023")]):
            self.assertTrue(ws.http_handover({"name": "cli", "actor": "human"}, "default")["ok"])
            self.assertTrue(ws.http_stop({"name": "cli", "actor": "human"}, "default")["ok"])
            self.assertTrue(ws.http_skip({"name": "cli"}, "default")["ok"])
        self.assertEqual(captured[0][0], "cli20261023")
        self.assertIn(f"[{q.id}]", captured[0][1])
        self.assertEqual(stopped, ["cli20261023"])
        st = sw.load_state("default")
        self.assertIn("cli20261023", st["ho_pending"])
        self.assertNotIn("cli", st["ho_pending"])
        self.assertIn("cli20261023", st["last_directive_at"])


if __name__ == "__main__":
    unittest.main()

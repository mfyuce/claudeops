"""Uzak projeye sahip cevabı yazımı (26 Kas, yuhem): dosya yoksa (200 + `files_not_found`) oluşturulur; geçici hata (okuma zaman
aşımı, host bayat/geri çekilmede) sessizce yeniden denenir, sahibe ancak uzun süre yazılamazsa bildirilir; değnekçinin İZLEDİĞİ
tireli adlı oturum proje klasörünü verir; geçici cevap iletim hatası hemen "İLETİLEMİYOR" olmaz.

Gerçek ağ/uzak host yok (`test_steward_remote_cards` düzeneği)."""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_steward_remote import HOST, _row  # noqa: E402
from test_steward_remote_cards import CWD, FilesHost, _Files, setUpModule, tearDownModule  # noqa: E402,F401
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

ANSWER = "yuhem adımını atla, açılınca yap"


class _Answers(_Files):
    def setUp(self):
        super().setUp()
        self.on()
        self.sent = []
        p = mock.patch.object(ws, "_notify", lambda cfg, text, *a, **kw: self.sent.append(text))
        p.start()
        self.addCleanup(p.stop)
        ws._ANSWER_FAILS.clear()
        ws._ANSWER_FAIL_SINCE.clear()

    def answer(self, project="oiso"):
        q = sw.add_question(project, "TBD#7 hangisi?", source="s")
        return q, ws.http_answer({"id": q.id, "answer": ANSWER}, "default")["persisted"]

    def pending(self):
        return sw.load_state(sw.paths_for("default")).get("persist_retry") or {}


class MissingFile(_Answers):
    def test_200_files_not_found_creates_file(self):
        self.fake.files = {}
        self.fake.missing = ({"ok": False, "error": "oiso: yol bulunamadı", "code": "files_not_found"}, 200)
        q, out = self.answer()
        self.assertEqual(out, {"tbd": "written", "todo": "written"})
        self.assertIn(f"[{q.id}]", self.fake.files[f"{CWD}/TOBEDECIDED.md"])
        self.assertTrue(all(p[2].get("create") for p in self.fake.posts))
        self.assertEqual((self.pending(), self.sent), ({}, []))

    def test_other_error_code_does_not_create(self):
        self.fake.files = {}
        self.fake.missing = ({"ok": False, "error": "x", "code": "not_running"}, 404)
        _q, out = self.answer()
        self.assertEqual(out["tbd"], "remote_unreadable")
        self.assertEqual(self.fake.posts, [])


class Retry(_Answers):
    def test_timeout_queued_silently_then_written(self):
        self.fake.down = True
        q, out = self.answer()
        self.assertEqual(out, {"tbd": "remote_unreadable", "todo": "remote_unreadable", "retry": "queued"})
        self.assertEqual((list(self.pending()), self.sent), ([q.id], []))
        t = time.time()
        self.fake.down = False
        ws._persist_retry_step("default", now=t)                       # vadesi gelmedi: istek yok
        self.assertEqual(self.fake.posts, [])
        ws._persist_retry_step("default", now=t + 120)
        self.assertIn(f"[{q.id}]", self.fake.files[f"{CWD}/TOBEDECIDED.md"])
        self.assertEqual((self.pending(), self.sent), ({}, []))

    def test_stale_host_notifies_once_after_30_min_and_gives_up_after_a_day(self):
        self.fake.set(HOST, [_row("oiso", running=False, cwd=CWD)], ok=False)
        q, out = self.answer()
        self.assertEqual((out["tbd"], out["retry"]), ("remote_denied", "queued"))
        t = time.time()
        for dt in (120, 600, 1200):
            ws._persist_retry_step("default", now=t + dt)
        self.assertEqual(self.sent, [])
        for dt in (1900, 2600, 3300):
            ws._persist_retry_step("default", now=t + dt)
        self.assertEqual(len(self.sent), 1)
        self.assertIn(q.id, self.sent[0])
        ws._persist_retry_step("default", now=t + 90000)
        self.assertEqual((self.pending(), len(self.sent)), ({}, 2))

    def test_remote_actions_off_notifies_at_once_without_queue(self):
        self.settings(remote_actions="off")
        _q, out = self.answer()
        self.assertEqual(out, {"tbd": "remote_denied", "todo": "remote_denied"})
        self.assertEqual((self.pending(), len(self.sent)), ({}, 1))

    def test_tick_keeps_queue_and_jobs_step_retries(self):
        self.fake.down = True
        q, _out = self.answer()
        ws.tick_once("manual", "default", cards=False)
        self.assertEqual(list(self.pending()), [q.id])
        with mock.patch.object(ws, "_persist_retry_step") as step:
            ws.jobs_fast_step()
        step.assert_called_with("default")


class OwnedSessionName(_Answers):
    def test_tracked_hyphen_session_gives_project_folder(self):
        name = "ancient-script-pipeline-fd20261118"
        sw.upsert_project("asp_fd", phase="paused", host=HOST)
        self.fake.set(HOST, [_row(name, running=True, cwd=CWD)])
        paths = sw.paths_for("default")
        with sw.steward_lock(paths):
            state = sw.load_state(paths)
            state["owned"] = {"asp_fd": name}
            sw.save_state(state, paths)
        self.fake.files = {f"{CWD}/TOBEDECIDED.md": "- TBD#7 soru\n", f"{CWD}/TODO.md": ""}
        _q, out = self.answer("asp_fd")
        self.assertEqual(out, {"tbd": "written", "todo": "written"})
        self.assertTrue(all(p[2]["name"] == name for p in self.fake.posts))


class DeliveryAlert(_Answers):
    def deliver(self, res, at):
        q = self.q
        action = sw.Action("deliver_answer", "oiso", "answer", {"question_id": q.id})
        with mock.patch.object(ws, "_give_directive", return_value=res), mock.patch.object(ws, "_target", return_value=None), \
                mock.patch.object(ws.time, "time", return_value=at):
            ws._apply(action, ws.steward_config(), sw.load_projects("default"), ws._world("default"))

    def test_transient_host_errors_alert_only_after_30_min(self):
        self.q = sw.add_question("oiso", "soru?", source="s")
        sw.answer_question(self.q.id, "evet", by="owner_panel")
        t = time.time()
        for i, res in enumerate(({"ok": False, "code": "host_down", "error": "target denied: host is unreachable"},
                                 {"ok": False, "error": "ulak31 unreachable: [Errno 104] Connection reset by peer"}) * 3):
            self.deliver(res, t + i * 60)
        self.assertEqual(self.sent, [])
        self.deliver({"ok": False, "code": "host_down", "error": "x"}, t + 1900)
        self.deliver({"ok": False, "code": "host_down", "error": "x"}, t + 1960)
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()

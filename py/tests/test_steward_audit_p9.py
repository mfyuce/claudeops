"""Çoklu değnekçi P9 denetim düzeltmeleri (Y1, Y2, O1-O4, D5, D8): her bulgunun yeniden üretimi.

Gerçek oturum/tmux/docker/ağ/servis YOK: `_Tmp` geçici dizin (settings + steward dizini), oturum işlemleri
(`_running`/`_send`/`is_tmux_backed`/`_project_running`/`mcp_queue._api`) sahte; hiçbir spawn yolu çağrılmaz.
Gerçek settings.json sha256'sı modül başında/sonunda karşılaştırılır.

Çalıştırma: python3 -m unittest discover -s py/tests"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import settings, steward as sw, steward_jobs as sj  # noqa: E402
from claudeops.commands import mcp_steward, steward as cli, web_steward as ws  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None


def _sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def setUpModule():
    global _HASH_BEFORE
    _HASH_BEFORE = _sha(_REAL_SETTINGS)


def tearDownModule():
    if _sha(_REAL_SETTINGS) != _HASH_BEFORE:
        raise AssertionError("gerçek ~/.claude/claudeops/settings.json test sırasında değişti")


class _Base(_Tmp):
    def setUp(self):
        super().setUp()
        ws._reset_contexts()
        ws.invalidate_summary()
        self.addCleanup(ws._reset_contexts)
        self.running = set()
        self.api_calls = []

        def fake_api(port, method, path, body=None):
            self.api_calls.append((method, path, body))
            return {"ok": True}

        for p in (mock.patch.object(cli.mcp_queue, "_api", fake_api),
                  mock.patch.object(cli, "_project_running", lambda name: name in self.running),
                  mock.patch.object(ws.web_ws, "notify_status_changed", lambda: None),
                  mock.patch.dict(os.environ, {}, clear=False)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(cli.ENV_STEWARD, None)

    def run_cli(self, *argv):
        ap = argparse.ArgumentParser()
        cli.register(ap.add_subparsers())
        args = ap.parse_args(["steward", *argv])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = args.func(args)
        return rc, out.getvalue()

    def make(self, sid="kitap", **extra):
        settings.save_settings({"stewards": {sid: dict({"label": "Kitaplar", "enabled": "off", "mode": "observe"}, **extra)}})
        os.makedirs(sw.paths_for(sid).root, exist_ok=True)


# ── Y1: devirden sonra telefon bağlantısı + CLI ipucu ─────────────────────────

class TestY1TransferredQuestionLink(_Base):
    def _asked_in_kitap_then_transferred(self):
        self.make()
        sw.upsert_project("kp", paths="kitap", phase="planned")
        q = sw.add_question("kp", "devir öncesi soru?", paths="kitap")
        sw.transfer_project("kp", "default")
        return q

    def test_old_link_with_the_previous_identity_still_finds_the_question_by_key(self):
        q = self._asked_in_kitap_then_transferred()
        self.assertIsNone(sw.find_question(q.id, "kitap"))
        self.assertIsNotNone(sw.find_question(q.id))
        st, _ = ws.http_question_page(q.id, q.key, False, None, "kitap")                # ntfy bağlantısı: ?s=kitap
        self.assertEqual(st, 200)
        st, _ = ws.http_question_page(q.id, q.key, False, {"answer": "evet"}, "kitap")
        self.assertEqual(st, 200)
        self.assertEqual(sw.find_question(q.id).answer, "evet")                          # cevap SAHİBİNİN (yeni) deposuna
        self.assertEqual(sw.find_question(q.id).status, "answered")

    def test_fallback_needs_the_key_not_just_the_id(self):
        q = self._asked_in_kitap_then_transferred()
        self.assertEqual(ws.http_question_page(q.id, "yanlış", False, None, "kitap")[0], 404)
        self.assertEqual(ws.http_question_page(q.id, "", True, None, "kitap")[0], 404)  # anahtarsız geri düşüş yok
        self.assertEqual(ws.http_question_page(q.id, q.key, False, None, "nope")[0], 404)   # bilinmeyen kimlik hâlâ 404

    def test_find_question_any_prefers_the_stated_store(self):
        self.make()
        a = sw.add_question("p", "d?")
        sid, q = ws._find_question_any(a.id, a.key, "default")
        self.assertEqual((sid, q.id), ("default", a.id))
        self.assertEqual(ws._find_question_any(a.id, "", "kitap"), ("", None))

    def test_cli_answer_reports_the_other_identity(self):
        q = self._asked_in_kitap_then_transferred()
        rc, out = self.run_cli("-s", "kitap", "answer", q.id, "evet")
        self.assertEqual(rc, 1)
        self.assertIn("başka kimlikte", out)
        self.assertIn("py/cops steward answer " + q.id, out)                            # default: -s bayrağı yok
        self.assertEqual(sw.find_question(q.id).status, "open")                          # CLI SESSİZCE cevaplamaz
        rc, out = self.run_cli("answer", "yok_id", "evet")
        self.assertEqual((rc, out.strip()), (1, "bilinmeyen soru id'si"))


# ── Y2: jobs ack yalnız terminal işte ─────────────────────────────────────────

class TestY2JobsAck(_Base):
    def _job(self, state):
        sj.save_record(sj.new_record("varaka", 17, "mkt", "noop", state, "idem"))

    def test_ack_on_an_open_job_is_refused_and_the_result_is_still_delivered_later(self):
        self._job("queued")
        rc, out = self.run_cli("jobs", "ack", "17")
        self.assertEqual(rc, 1)
        self.assertIn("açık", out)
        job = sj.find_job(sj.load_jobs(), 17)
        self.assertFalse(job.get("delivered"))
        sj.update_records({("varaka", "17"): {"state": "done"}})
        self.assertEqual(sj.pending_stage(sj.find_job(sj.load_jobs(), 17)), "result")   # sonuç hâlâ iletilecek

    def test_ack_on_a_terminal_job_still_works(self):
        self._job("done")
        rc, out = self.run_cli("jobs", "ack", "17")
        self.assertEqual(rc, 0, out)
        self.assertTrue(sj.find_job(sj.load_jobs(), 17)["delivered"])

    def test_ack_on_an_unknown_state_is_refused_too(self):
        self._job("paused")
        self.assertEqual(self.run_cli("jobs", "ack", "17")[0], 1)
        self.assertFalse(sj.find_job(sj.load_jobs(), 17).get("delivered"))


# ── O1: beyin yeni ad açamaz ──────────────────────────────────────────────────

class TestO1BrainCannotCreateProjects(_Base):
    def test_brain_upsert_of_a_new_name_is_refused_but_existing_updates_work(self):
        r = ws.http_post("/api/steward/project", {"name": "egyptian", "phase": "planned", "actor": "brain"})
        self.assertFalse(r["ok"])
        self.assertNotIn("egyptian", sw.load_projects())
        sw.upsert_project("mkt", phase="planned")
        r = ws.http_post("/api/steward/project", {"name": "mkt", "phase": "paused", "actor": "brain"})
        self.assertFalse(r["ok"])      # beyin projeyi paused/done yapamaz (27 Eki): sahibin kararı
        r = ws.http_post("/api/steward/project", {"name": "mkt", "notes": "n", "actor": "brain"})
        self.assertTrue(r["ok"])
        self.assertEqual(sw.load_projects()["mkt"].phase, "planned")

    def test_human_may_still_create_a_project(self):
        r = ws.http_post("/api/steward/project", {"name": "yeni", "phase": "planned"})
        self.assertTrue(r["ok"])
        self.assertIn("yeni", sw.load_projects())

    def test_brain_refusal_applies_in_other_identities_and_the_mcp_tool_marks_the_actor(self):
        self.make()
        r = ws.http_post("/api/steward/project", {"name": "egyptian", "actor": "brain", "steward": "kitap"})
        self.assertFalse(r["ok"])
        self.assertEqual(sw.load_projects("kitap"), {})
        mcp_steward._set_project(1, {"name": "p", "phase": "planned"})
        self.assertEqual(self.api_calls[-1][2].get("actor"), "brain")                    # sunucu kaynağı bilsin


# ── O2: bilinmeyen uzak durum ─────────────────────────────────────────────────

class TestO2UnknownRemoteState(_Base):
    def setUp(self):
        super().setUp()
        sj.reset_backoff()
        self.addCleanup(sj.reset_backoff)
        tf = os.path.join(self.dir.name, "t.token")
        with open(tf, "w") as f:
            f.write("tok\n")
        os.chmod(tf, 0o600)
        sj.add_service("varaka", "http://127.0.0.1:1", tf)       # hiçbir istek yapılmaz: `fetch` sahte
        sj.save_record(sj.new_record("varaka", 5, "mkt", "noop", "queued", "idem"))

    def test_an_unknown_state_stays_open_keeps_polling_and_is_logged_once(self):
        fetch = lambda svc, path: (200, {"id": 5, "state": "paused", "requester": "mkt"})  # noqa: E731
        t = time.time()
        sj.poll_jobs("default", now=t, force=True, fetch=fetch)
        job = sj.find_job(sj.load_jobs(), 5)
        self.assertEqual(job["state"], "paused")
        self.assertTrue(sj.is_open(job))
        self.assertEqual(len(sj.due_jobs(sj.load_jobs(), t + 1000)), 1)                  # yoklama sürer
        res = sj.poll_jobs("default", now=t + 1000, fetch=fetch)
        self.assertEqual(res["polled"], 1)
        self.assertEqual(len([e for e in sw.tail_log(50) if e["event"] == "job_unknown_state"]), 1)   # tek seferlik
        done = lambda svc, path: (200, {"id": 5, "state": "done", "requester": "mkt"})  # noqa: E731
        sj.poll_jobs("default", now=t + 2000, fetch=done)
        self.assertEqual(sj.pending_stage(sj.find_job(sj.load_jobs(), 5)), "result")

    def test_known_states_unchanged(self):
        for st in sj.OPEN_STATES:
            self.assertTrue(sj.is_open({"state": st}))
        for st in sj.TERMINAL_STATES:
            self.assertFalse(sj.is_open({"state": st}))
        self.assertFalse(sj.is_open({}))
        self.assertFalse(sj.is_open({"state": ""}))


# ── O3: transfer yazım sırası ─────────────────────────────────────────────────

class TestO3TransferWriteOrder(_Base):
    def _setup(self):
        self.make()
        sw.upsert_project("kp", phase="planned")
        jp = sw.paths_for().jobs
        os.makedirs(os.path.dirname(jp), exist_ok=True)
        with open(jp, "w", encoding="utf-8") as f:
            json.dump([{"id": 1, "service": "varaka", "project": "kp", "state": "done"}], f)
        sw.add_question("kp", "soru?")

    def _fail_on(self, path):
        real = sw._save_json

        def flaky(p, data):
            if os.path.abspath(p) == os.path.abspath(path):
                raise OSError("disk dolu (sahte)")
            return real(p, data)
        return mock.patch.object(sw, "_save_json", flaky)

    def test_failure_writing_the_destination_leaves_everything_at_the_source(self):
        self._setup()
        with self._fail_on(sw.paths_for("kitap").projects), self.assertRaises(OSError):
            sw.transfer_project("kp", "kitap")
        self.assertIn("kp", sw.load_projects())
        self.assertEqual(sw.load_projects("kitap"), {})
        self.assertEqual([j["id"] for j in sj.load_jobs()], [1])                         # işler kaynakta
        self.assertEqual(sj.load_jobs("kitap"), [])
        self.assertEqual(len(sw.load_questions()), 1)

    def test_failure_writing_the_source_leaves_the_name_in_both_places_and_loses_nothing(self):
        self._setup()
        with self._fail_on(sw.paths_for().projects), self.assertRaises(OSError):
            sw.transfer_project("kp", "kitap")
        self.assertIn("kp", sw.load_projects())
        self.assertIn("kp", sw.load_projects("kitap"))                                   # çakışma = kimse yönetmez (güvenli)
        self.assertEqual([j["id"] for j in sj.load_jobs()], [1])                         # kaynak kaydı kaybolmadı
        self.assertEqual([j["id"] for j in sj.load_jobs("kitap")], [1])
        self.assertEqual(len(sw.load_questions("kitap")), 1)

    def test_successful_transfer_unchanged(self):
        self._setup()
        self.assertEqual(sw.transfer_project("kp", "kitap"), "default")
        self.assertEqual((sw.load_projects(), sj.load_jobs()), ({}, []))
        self.assertEqual(set(sw.load_projects("kitap")), {"kp"})
        self.assertEqual([j["id"] for j in sj.load_jobs("kitap")], [1])
        self.assertEqual(len(sw.load_questions("kitap")), 1)


# ── O4: çıkarılmış kimliğin çalışan beyni ─────────────────────────────────────

class TestO4OrphanBrain(_Base):
    def test_degnekci_family_without_an_owner_is_another_brain_not_adhoc(self):
        world = sw.world_for("default", {"brains": {}, "owners": {}, "conflicts": [], "services": {}})
        self.assertEqual(world.session_class("degnekci_kitap"), "brain_other")
        self.assertEqual(world.name_class("degnekci_eski"), "brain_other")
        self.assertEqual(world.session_class("degnekci"), "brain_own")                    # kendi beyni değişmedi
        self.assertEqual(world.session_class("egyptian"), "adhoc")

    def test_remove_refuses_while_the_identity_brain_runs(self):
        self.make()
        self.running.add("degnekci_kitap")
        rc, out = self.run_cli("remove", "kitap")
        self.assertEqual(rc, 1)
        self.assertIn("degnekci_kitap", out)
        self.assertTrue(os.path.isdir(sw.paths_for("kitap").root))
        self.assertIn("kitap", settings.steward_ids())
        self.running.clear()
        self.assertEqual(self.run_cli("remove", "kitap")[0], 0)
        self.assertNotIn("kitap", settings.steward_ids())


# ── D5: mesaj gittikten sonra kilit zaman aşımı ───────────────────────────────

class TestD5LockTimeoutAfterSend(_Base):
    def setUp(self):
        super().setUp()
        self.sent = []
        ws._SENT_UNMARKED.clear()
        self.addCleanup(ws._SENT_UNMARKED.clear)
        sw.upsert_project("mkt", phase="planned")
        self.p = sw.load_projects()["mkt"]
        s = NS(name="mkt", cli="claude", pid=1)
        for p in (mock.patch.object(ws, "_running", lambda name: s),
                  mock.patch.object(ws, "is_tmux_backed", lambda pid: True),
                  mock.patch.object(ws, "_send", lambda name, c, msg: self.sent.append(msg) or True)):
            p.start()
            self.addCleanup(p.stop)
        q = sw.add_question("mkt", "soru?")
        sw.answer_question(q.id, "evet")
        self.q = sw.find_question(q.id)

    def test_lock_timeout_while_recording_the_directive_does_not_unmark_the_delivery(self):
        def boom(*a, **k):
            raise sw.LockTimeout("sahte")
        with mock.patch.object(sw, "upsert_project", boom):
            res = ws._give_directive(self.p, "devam", answer=self.q, start_if_stopped=False)
        self.assertTrue(res["ok"])
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(sw.find_question(self.q.id).delivered_at)                         # cevap yeniden iletilmez
        self.assertTrue([e for e in sw.tail_log(20) if e["event"] == "directive_unrecorded"])

    def test_a_single_lock_timeout_on_the_delivery_mark_is_retried(self):
        real, calls = sw.mark_delivered, []

        def flaky(qid, paths=None):
            calls.append(qid)
            if len(calls) == 1:
                raise sw.LockTimeout("sahte")
            return real(qid, paths)
        with mock.patch.object(sw, "mark_delivered", flaky):
            res = ws._give_directive(self.p, "devam", answer=self.q, start_if_stopped=False)
        self.assertTrue(res["ok"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(sw.find_question(self.q.id).delivered_at)

    def test_persistent_lock_timeout_on_the_mark_is_logged_not_raised(self):
        def boom(*a, **k):
            raise sw.LockTimeout("sahte")
        with mock.patch.object(sw, "mark_delivered", boom):
            res = ws._give_directive(self.p, "devam", answer=self.q, start_if_stopped=False)
        self.assertTrue(res["ok"])                                                       # mesaj GİTTİ: başarısız gösterme
        self.assertTrue(res.get("unrecorded"))
        self.assertTrue([e for e in sw.tail_log(20) if e["event"] == "delivery_unrecorded"])

    def test_next_tick_does_not_resend_what_already_went_out(self):
        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise sw.LockTimeout("sahte")
        with mock.patch.object(sw, "mark_delivered", boom):
            ws._give_directive(self.p, "devam", answer=self.q, start_if_stopped=False)
            self.assertEqual(len(self.sent), 1)
            res = ws._give_directive(self.p, "devam", answer=self.q, start_if_stopped=False)       # sonraki tick
        self.assertEqual(len(self.sent), 1)                                              # yinelenen iletim YOK
        self.assertEqual(res.get("skipped"), "already sent")
        ws._give_directive(self.p, "devam", answer=self.q, start_if_stopped=False)       # kilit düzeldi: işaret yazılır
        self.assertTrue(sw.find_question(self.q.id).delivered_at)
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn(("default", "answer", self.q.id), ws._SENT_UNMARKED)

    def test_job_delivery_mark_timeout_is_not_raised_either(self):
        sj.save_record(sj.new_record("varaka", 9, "mkt", "noop", "done", "idem"))
        action = sw.Action("deliver_job", "mkt", "job", {"job_id": 9, "service": "varaka", "stage": "result"})

        def boom(*a, **k):
            raise sw.LockTimeout("sahte")
        with mock.patch.object(sj, "mark_delivered", boom):
            res = ws._deliver_job(action, ws.steward_config(), sw.load_projects())
        self.assertTrue(res["ok"])


# ── D8: devir hedefi ayarda tanımlı olmalı ────────────────────────────────────

class TestD8TransferTargetMustBeConfigured(_Base):
    def test_unconfigured_target_is_refused_without_creating_a_directory(self):
        sw.upsert_project("kp", phase="planned")
        with self.assertRaises(ValueError):
            sw.transfer_project("kp", "yeni")
        self.assertFalse(os.path.exists(sw.paths_for("yeni").root))
        self.assertIn("kp", sw.load_projects())

    def test_configured_target_and_default_still_work(self):
        self.make()
        sw.upsert_project("kp", phase="planned")
        self.assertEqual(sw.transfer_project("kp", "kitap"), "default")
        self.assertEqual(sw.transfer_project("kp", "default"), "kitap")


if __name__ == "__main__":
    unittest.main()

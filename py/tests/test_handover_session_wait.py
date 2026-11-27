"""27 Kas 20:38: devir metni, transkript denetimi yüklüyken açık soru diyaloğuna cevap olarak düştü. claude'un süreç kaydı
(`sessions/<pid>.json`, `status: waiting`) transkriptten ve oturum kimliğinden bağımsız ikinci sinyaldir. Gerçek oturum YOK."""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import handover, paths, steward as sw  # noqa: E402
from claudeops.commands import web, web_steward as ws  # noqa: E402

PID = 4242
ASK = json.dumps({"type": "assistant", "message": {"id": "m", "content": [
    {"type": "tool_use", "id": "t", "name": "AskUserQuestion", "input": {}}]}})


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        self.transcript = os.path.join(d.name, "s.jsonl")
        open(self.transcript, "w").close()
        for p in (mock.patch.object(paths, "SESSIONS_DIR", d.name),
                  mock.patch.object(handover, "jsonl_path_for", lambda *a: self.transcript),
                  mock.patch("claudeops.providers.claude_provider.jsonl_path_for", lambda *a: self.transcript)):
            p.start()
            self.addCleanup(p.stop)

    def record(self, status, waiting_for=None, pid=PID, file_pid=None):
        doc = {"pid": pid, "status": status}
        if waiting_for:
            doc["waitingFor"] = waiting_for
        with open(os.path.join(self.dir, f"{file_pid or pid}.json"), "w") as f:
            json.dump(doc, f)


class WebHandover(Base):
    def run_handover(self, cli="claude"):
        proc = SimpleNamespace(name="a", pid=PID, cli=cli, cwd="/w", sid="s", model="", effort="")
        sent = []
        with mock.patch.object(web, "_find_running_for_action", lambda n: ("exact", [proc])), \
                mock.patch.object(web, "is_tmux_backed", lambda p: True), \
                mock.patch.object(web, "apply_handover_downgrades",
                                  lambda *a, **k: sent.append("model") or handover.HandoverDowngrade()), \
                mock.patch.object(web, "tmux_send_keys", lambda *a, **k: sent.append("keys") or True), \
                mock.patch.object(web.get_provider(cli), "dismiss_stray_dialog", lambda *a: None):
            return web._handover("a"), sent

    def test_waiting_session_gets_no_keys_even_if_transcript_is_silent(self):
        for waiting_for in ("input needed", "dialog open", None):
            with self.subTest(waiting_for=waiting_for):
                self.record("waiting", waiting_for)
                res, sent = self.run_handover()
                self.assertEqual((res["ok"], res.get("code"), sent), (False, "question_open", []))

    def test_other_states_do_not_block(self):
        cases = (lambda: self.record("idle"), lambda: self.record("busy"),
                 lambda: self.record("waiting", "input needed", pid=7, file_pid=PID),      # başka sürecin kaydı
                 lambda: open(os.path.join(self.dir, f"{PID}.json"), "w").write("[bozuk"))
        for i, prepare in enumerate(cases):
            with self.subTest(case=i):
                prepare()
                res, sent = self.run_handover()
                self.assertEqual((res["ok"], sent), (True, ["model", "keys"]))


class SteerView(Base):
    def test_waiting_for_input_counts_as_open_question(self):
        self.record("waiting", "input needed")
        self.assertTrue(ws.owner_dialog_for("/w", "s", "claude", PID)[0])
        self.assertFalse(ws.owner_dialog_for("/w", "s", "codex", PID)[0])

    def test_other_waits_do_not_freeze_the_planner(self):
        self.record("waiting", "dialog open")
        self.assertFalse(ws.owner_dialog_for("/w", "s", "claude", PID)[0])


class BatchHandover(Base):
    def run_faz1(self):
        s = SimpleNamespace(name="a", base="a", pid=PID, cli="claude", cwd="/w", sid="s", model="", effort="")
        sent = []
        with mock.patch.object(handover, "find_sessions", lambda **k: [s]), \
                mock.patch.object(handover, "ancestor_pids", lambda: set()), \
                mock.patch.object(handover, "is_tmux_backed", lambda p: True), \
                mock.patch.object(handover, "apply_handover_downgrades",
                                  lambda *a, **k: sent.append("model") or handover.HandoverDowngrade()), \
                mock.patch.object(handover, "tmux_send_keys", lambda *a, **k: sent.append("keys") or True), \
                mock.patch.object(paths, "STATE_DIR", __import__("pathlib").Path(self.dir)), \
                mock.patch("builtins.print"):
            summary = handover.handover_faz1(names=["a"])
        return [r.status for r in summary.results], sent

    def test_batch_skips_waiting_session(self):
        self.record("waiting", "input needed")
        self.assertEqual(self.run_faz1(), (["skipped-dialog"], []))

    def test_batch_skips_open_question_in_transcript(self):
        self.record("busy")
        with open(self.transcript, "w") as f:
            f.write(ASK + "\n")
        self.assertEqual(self.run_faz1(), (["skipped-dialog"], []))


class EngineDelivery(Base):
    """Devir dışındaki motor yazımları (direktif, cevap, ders, iş, dürtme) da açık diyaloğa tuş basmaz."""
    def setUp(self):
        super().setUp()
        self.cfg = sw.Config(enabled=True)
        self.proc = SimpleNamespace(name="a", pid=PID, cli="claude", cwd="/w", sid="s", model="", effort="")
        self.sent = []
        for p in (mock.patch.object(ws, "_send", lambda *a, **k: self.sent.append(a[2]) or True),
                  mock.patch.object(ws, "_running", lambda n: self.proc),
                  mock.patch.object(ws, "_live_sessions", lambda *a: [self.proc]),
                  mock.patch.object(ws, "is_tmux_backed", lambda p: True),
                  mock.patch.object(ws, "_live_ho_done", lambda s: False),
                  mock.patch.object(ws, "_name_host", lambda n: ""),
                  mock.patch.object(ws, "_proc_born", lambda pid: 0.0),
                  mock.patch.object(ws, "_box_has_typed_input", lambda *a: False),
                  mock.patch.object(ws, "_target", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        self.record("waiting", "dialog open")

    def assert_refused(self, res):
        self.assertEqual((res["ok"], res.get("code"), self.sent), (False, "question_open", []))

    def test_directive(self):
        self.assert_refused(ws._give_directive(sw.Project(name="a"), "iş", cfg=self.cfg, reason="job", start_if_stopped=False))

    def test_directive_goes_through_when_idle(self):
        self.record("idle")
        self.assertTrue(ws._give_directive(sw.Project(name="a"), "iş", cfg=self.cfg, reason="job", start_if_stopped=False)["ok"])
        self.assertEqual(len(self.sent), 1)

    def test_nudges(self):
        for kind in ("keepwarm", "idle_nudge", "owner_todo_move", "todo_triage", "nudge"):
            with self.subTest(kind=kind):
                self.sent.clear()
                self.assert_refused(ws._apply(sw.Action(kind, "a", "x", {}), self.cfg, {}))

    def test_brain_tour(self):
        self.proc.name = self.cfg.brain_name
        with mock.patch.object(ws, "brain_start", lambda *a: {"ok": True, "started": True}):
            self.assert_refused(ws.run_tour(items=[{"kind": "routine", "name": "-", "id": "x", "text": "y"}], cfg=self.cfg))

    def test_refusal_does_not_use_up_lesson_or_job_attempts(self):
        proj = {"a": sw.Project(name="a")}
        act = sw.Action("deliver_lesson", "a", "lesson", {"project": "a", "hashes": ["h1"], "lines": ["ders"]})
        self.assert_refused(ws._deliver_lesson(act, self.cfg, proj))
        self.assertFalse(sw.load_state(sw.paths_for(self.cfg.sid)).get("lessons_fail"))
        job = {"id": 1, "project": "a"}
        marked = []
        with mock.patch.object(ws.sj, "find_job", lambda *a: job), mock.patch.object(ws.sj, "load_jobs", lambda *a: []), \
                mock.patch.object(ws.sj, "pending_stage", lambda j: "result"), mock.patch.object(ws.sj, "build_job_message", lambda *a: "sonuç"), \
                mock.patch.object(ws.sj, "mark_attempt", lambda *a: marked.append(a) or 1):
            self.assert_refused(ws._deliver_job(sw.Action("deliver_job", "a", "job", {"job_id": 1, "service": "v", "stage": "result"}), self.cfg, proj))
        self.assertEqual(marked, [])

    def test_unregistered_answer_is_kept_and_not_reported(self):
        q = sw.add_question("adhoc-dialog", "soru metni burada?")
        sw.answer_question(q.id, "evet")
        notes = []
        ws._ANSWER_FAILS.clear()
        with mock.patch.object(ws, "_notify", lambda c, m: notes.append(m) or True):
            for _ in range(ws.ANSWER_FAIL_ALERT + 1):
                self.assert_refused(ws._apply(sw.Action("deliver_answer", "a", "answer", {"question_id": q.id}), self.cfg, {}))
        self.assertEqual(notes, [])
        self.assertIn(q.id, [x.id for x in sw.undelivered_answers()])


class TermInput(Base):
    def run_input(self, auto):
        proc = SimpleNamespace(name="a", pid=PID, cli="claude", cwd="/w", sid="s")
        sent = []
        with mock.patch.object(web, "_term_resolve", lambda *a, **k: (proc, None)), \
                mock.patch.object(web, "pane_is_masked_input", lambda n: False), \
                mock.patch.object(web.web_ws, "notify_term_activity", lambda n: None), \
                mock.patch.object(web, "tmux_send_keys", lambda *a, **k: sent.append("keys") or True):
            return web._term_input("a", "metin", auto=auto), sent

    def test_engine_input_is_refused_but_owner_typing_is_not(self):
        self.record("waiting", "input needed")
        res, sent = self.run_input(True)
        self.assertEqual((res["ok"], res.get("code"), sent), (False, "question_open", []))
        res, sent = self.run_input(False)
        self.assertEqual((res["ok"], sent), (True, ["keys"]))


if __name__ == "__main__":
    unittest.main()

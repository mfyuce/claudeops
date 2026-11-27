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
from claudeops import handover, paths  # noqa: E402
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
                mock.patch.object(web, "apply_handover_downgrades", lambda *a, **k: sent.append("model")), \
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
                mock.patch.object(handover, "apply_handover_downgrades", lambda *a, **k: sent.append("model")), \
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


if __name__ == "__main__":
    unittest.main()

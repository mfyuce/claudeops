"""`/api/agents/*` mantığı (`web_agents`) sahte `ops` ile: gerçek spawn/tmux/ağ YOK, kayıt defteri geçici dizinde."""
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_agents as ag  # noqa: E402
from claudeops import ucli_client as uc  # noqa: E402
from claudeops.commands import web_agents as wa  # noqa: E402

CATALOG = [{"id": "m-evren", "service": "evren", "efforts": ["medium", "high"]},
           {"id": "claude-sonnet-5-5", "service": "claude", "efforts": ["low", "medium", "high"]}]


class FakeOps:
    def __init__(self, parent_mode="read-only"):
        self.live = {"p": NS(name="p", cli="ucli", cwd="/proj", permission_mode=parent_mode)}
        self.calls = []
        self.start_result = {"ok": True}
        self.send_result = {"ok": True}
        self.taken = set()

    def sessions(self):
        return list(self.live.values())

    def name_taken(self, name):
        return name in self.taken

    def register(self, name, cwd, model, mode, effort):
        self.calls.append(("register", name, cwd, mode))

    def forget(self, name):
        self.calls.append(("forget", name))

    def start(self, name, model, permission_mode, effort, cli_opts):
        self.calls.append(("start", name, model, permission_mode, effort, dict(cli_opts)))
        if self.start_result.get("ok"):
            self.live[name] = NS(name=name, cli="ucli", cwd="/proj", permission_mode=permission_mode)
        return self.start_result

    def stop(self, name):
        self.calls.append(("stop", name))
        self.live.pop(name, None)
        return {"ok": True}

    def send(self, name, text):
        self.calls.append(("send", name, text))
        return self.send_result


class WaBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ops = FakeOps()
        patches = [
            mock.patch.object(ag, "STATE_FILE", os.path.join(tmp.name, "a.json")),
            mock.patch.object(ag, "TOKEN_DIR", os.path.join(tmp.name, "t")),
            mock.patch.object(ag, "enabled", lambda: True),
            mock.patch.object(ag, "max_cost_usd", lambda: 2.0),
            mock.patch.object(wa, "models_catalog", lambda: CATALOG),
            mock.patch.object(wa, "diag_log", lambda *a, **k: None),
            mock.patch.object(wa, "_cost_usd", lambda name: 0.5),
            mock.patch.object(uc, "read_status_file", lambda cwd, n: self.status),
            mock.patch.object(uc, "read_chat_history", lambda cwd, n: self.history),
        ]
        self.status, self.history = None, []
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        wa._MISSES.clear()

    AGENT = ("agent", "p")

    def start(self, caller=AGENT, **kw):
        data = {"model": "m-evren", "effort": "high", "task": "do it\nnow", "mode": "read"}
        data.update(kw)
        return wa.handle_post("/api/agents/start", data, caller, self.ops)


class StartTests(WaBase):
    def test_start_ok_folds_task_and_passes_limits(self):
        body, st = self.start()
        self.assertEqual((body, st), ({"ok": True, "name": "p_aj1"}, 200))
        start = next(c for c in self.ops.calls if c[0] == "start")
        self.assertEqual(start[3], "read-only")
        self.assertEqual(start[5], {"service": "evren", "max_cost_usd": 2.0})
        self.assertIn(("send", "p_aj1", "do it now"), self.ops.calls)
        self.assertEqual(ag.get_child("p_aj1")["parent"], "p")

    def test_third_live_child_refused(self):
        self.assertTrue(self.start()[0]["ok"])
        self.assertTrue(self.start()[0]["ok"])
        body, st = self.start()
        self.assertFalse(body["ok"])
        self.assertEqual(st, 429)

    def test_edit_needs_allow_edit_parent(self):
        body, st = self.start(mode="edit")
        self.assertFalse(body["ok"])
        self.assertEqual(st, 403)
        self.ops.live["p"].permission_mode = "allow-edit"
        body, _ = self.start(mode="edit")
        self.assertTrue(body["ok"])
        self.assertEqual([c for c in self.ops.calls if c[0] == "start"][0][3], "allow-edit")

    def test_validation(self):
        for kw in ({"model": "nope"}, {"effort": "max"}, {"mode": "root"}, {"task": "  "}, {"model": ""}):
            self.assertFalse(self.start(**kw)[0]["ok"], kw)
        self.assertFalse(self.start(effort="low")[0]["ok"])             # m-evren effort low desteklemiyor
        self.assertTrue(self.start(model="claude-sonnet-5-5", effort="low")[0]["ok"])

    def test_child_cannot_start_and_parent_must_run(self):
        self.ops.live["p_aj1"] = NS(name="p_aj1", cli="ucli", cwd="/proj", permission_mode="read-only")
        body, st = self.start(caller=("agent", "p_aj1"))
        self.assertEqual(st, 403)
        del self.ops.live["p"]
        self.assertEqual(self.start()[1], 409)

    def test_human_needs_parent(self):
        self.assertFalse(self.start(caller=("human", ""))[0]["ok"])
        self.assertTrue(self.start(caller=("human", ""), parent="p")[0]["ok"])

    def test_start_failure_releases_and_forgets(self):
        self.ops.start_result = {"ok": False, "error": "boom"}
        body, st = self.start()
        self.assertEqual((body["ok"], body["error"], st), (False, "boom", 502))
        self.assertIn(("forget", "p_aj1"), self.ops.calls)
        self.ops.start_result = {"ok": True}
        self.assertTrue(self.start()[0]["ok"])          # ayrılan yuva tükenmedi

    def test_task_not_delivered_stops_child(self):
        self.ops.send_result = {"ok": False}
        body, _ = self.start()
        self.assertFalse(body["ok"])
        self.assertIn(("stop", "p_aj1"), self.ops.calls)

    def test_disabled(self):
        with mock.patch.object(ag, "enabled", lambda: False):
            self.assertEqual(self.start()[1], 403)
            self.assertEqual(wa.handle_get("/api/agents/models", {}, self.AGENT, self.ops)[1], 403)


class QueryTests(WaBase):
    def setUp(self):
        super().setUp()
        self.start()

    def q(self, path, name="p_aj1", caller=WaBase.AGENT):
        return wa.handle_get(path, {"name": [name]}, caller, self.ops)

    def test_models(self):
        body, st = wa.handle_get("/api/agents/models", {}, self.AGENT, self.ops)
        self.assertEqual((st, body["models"]), (200, CATALOG))

    def test_status_states(self):
        self.status = {"activity": "waiting_for_model", "turns": 3}
        self.assertEqual(self.q("/api/agents/status")[0], {"ok": True, "state": "busy", "cost_usd": 0.5, "turns": 3})
        self.status = {"activity": "waiting_for_stdin", "turns": 1}
        ag.update_child("p_aj1", last_input_at=time.time() - 60)
        self.assertEqual(self.q("/api/agents/status")[0]["state"], "idle")
        ag.update_child("p_aj1", last_input_at=time.time())
        self.assertEqual(self.q("/api/agents/status")[0]["state"], "busy")      # girdi hemen gönderildi
        self.ops.stop("p_aj1")
        ag.mark_stopped("p_aj1")
        self.assertEqual(self.q("/api/agents/status")[0]["state"], "stopped")

    def test_result_is_last_assistant_after_last_user(self):
        self.status = {"activity": "waiting_for_stdin"}
        ag.update_child("p_aj1", last_input_at=0)
        self.history = [{"role": "user", "text": "q"}, {"role": "assistant", "text": "old"},
                        {"role": "user", "text": "q2"}, {"role": "tool", "text": "x"},
                        {"role": "assistant", "text": "answer"}, {"role": "assistant", "text": ""}]
        self.assertEqual(self.q("/api/agents/result")[0], {"ok": True, "state": "idle", "answer": "answer"})
        self.history.append({"role": "user", "text": "q3"})
        self.assertEqual(self.q("/api/agents/result")[0]["answer"], "")

    def test_result_readable_after_stop(self):
        self.history = [{"role": "user", "text": "q"}, {"role": "assistant", "text": "done"}]
        wa.handle_post("/api/agents/stop", {"name": "p_aj1"}, self.AGENT, self.ops)
        body, _ = self.q("/api/agents/result")
        self.assertEqual((body["state"], body["answer"]), ("stopped", "done"))

    def test_other_parent_cannot_see_or_touch(self):
        other = ("agent", "zzz")
        self.assertEqual(self.q("/api/agents/status", caller=other)[1], 404)
        self.assertEqual(wa.handle_post("/api/agents/stop", {"name": "p_aj1"}, other, self.ops)[1], 404)
        self.assertEqual(wa.handle_post("/api/agents/send", {"name": "p_aj1", "text": "x"}, other, self.ops)[1], 404)
        self.assertEqual(self.q("/api/agents/status", caller=("human", ""))[1], 200)
        self.assertEqual(self.q("/api/agents/status", name="nonexistent")[1], 404)

    def test_send_folds_and_refuses_stopped(self):
        body, _ = wa.handle_post("/api/agents/send", {"name": "p_aj1", "text": "a\nb"}, self.AGENT, self.ops)
        self.assertTrue(body["ok"])
        self.assertIn(("send", "p_aj1", "a b"), self.ops.calls)
        wa.handle_post("/api/agents/stop", {"name": "p_aj1"}, self.AGENT, self.ops)
        self.assertEqual(wa.handle_post("/api/agents/send", {"name": "p_aj1", "text": "x"}, self.AGENT, self.ops)[1], 409)


class LifecycleTests(WaBase):
    def test_parent_closed_stops_children_and_revokes(self):
        tok = open(ag.issue_token("p")).read()
        self.start()
        self.start()
        stopped = wa.parent_closed("p", self.ops)
        self.assertEqual(sorted(stopped), ["p_aj1", "p_aj2"])
        self.assertEqual([c for c in self.ops.calls if c[0] == "stop"], [("stop", "p_aj1"), ("stop", "p_aj2")])
        self.assertIsNone(ag.parent_for_token(tok))
        self.assertEqual(ag.get_child("p_aj1")["status"], "stopped")

    def test_reap_debounces_then_closes_orphans(self):
        self.start()
        del self.ops.live["p"]
        self.assertEqual(wa.reap(self.ops), [])             # ilk gözlem: bekle
        self.assertIn("p_aj1", self.ops.live)
        self.assertEqual(wa.reap(self.ops), ["p_aj1"])      # ikinci art arda gözlem: çocuklar kapanır
        self.assertEqual(ag.get_child("p_aj1")["status"], "stopped")

    def test_reap_keeps_children_when_discovery_fails(self):
        self.start()
        self.ops.sessions = mock.Mock(side_effect=RuntimeError("boom"))
        for _ in range(3):
            wa.reap(self.ops)
        self.assertEqual(ag.get_child("p_aj1")["status"], "running")

    def test_reap_enforces_cost_cap(self):
        self.start()
        with mock.patch.object(wa, "_cost_usd", lambda n: 2.5):
            self.assertEqual(wa.reap(self.ops), ["p_aj1"])
        self.assertEqual(ag.get_child("p_aj1")["reason"], "cost_cap")
        self.assertIn(("stop", "p_aj1"), self.ops.calls)


if __name__ == "__main__":
    unittest.main()

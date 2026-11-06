"""Beynin `paused` yetkisi (sahip TBD#163 b): saf karar + http_project_upsert kapısı. Gerçek oturum/ağ YOK."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

NOW = 1_000_000.0
OLD = NOW - 3 * 86400


class TestVerdict(unittest.TestCase):
    def v(self, card, running=False, reason="sahibe bağlı", now=NOW):
        return sw.brain_pause_verdict(card, running, reason, now=now)

    def test_finished_project_is_accepted(self):
        self.assertEqual(self.v({"last_activity": OLD, "next_step": "", "open_tbds": [], "blockers": []}), (True, ""))

    def test_blocked_project_with_open_work_is_accepted(self):
        self.assertTrue(self.v({"last_activity": OLD, "next_step": "x", "blockers": ["sahip"]})[0])

    def test_refusals(self):
        done = {"last_activity": OLD}
        self.assertFalse(self.v(done, reason="")[0])
        self.assertFalse(self.v(done, running=True)[0])
        self.assertFalse(self.v(None)[0])
        self.assertFalse(self.v({"last_activity": NOW - 3600})[0])
        self.assertFalse(self.v({"last_activity": OLD, "next_step": "devam"})[0])
        self.assertFalse(self.v({"last_activity": OLD, "open_tbds": ["TBD#1"]})[0])


class TestGate(_Tmp):
    def setUp(self):
        super().setUp()
        ws._reset_contexts()
        self.addCleanup(ws._reset_contexts)
        sw.upsert_project("mkt", phase="planned")
        live = []
        self.live = live
        for p in (mock.patch.object(ws, "_live_sessions", lambda n, sid="default": list(live)),
                  mock.patch.object(ws, "_notify", lambda *a, **k: True)):
            p.start()
            self.addCleanup(p.stop)

    def pause(self, **extra):
        return ws.http_post("/api/steward/project", dict({"name": "mkt", "phase": "paused", "actor": "brain"}, **extra))

    def test_accepted_when_finished_and_logged(self):
        with mock.patch.object(sw, "load_card", lambda n, paths=None: {"last_activity": OLD}):
            r = self.pause(reason="bitti")
        self.assertTrue(r["ok"], r)
        self.assertEqual(sw.load_projects()["mkt"].phase, "paused")

    def test_refused_when_work_should_continue(self):
        with mock.patch.object(sw, "load_card", lambda n, paths=None: {"last_activity": OLD, "next_step": "devam"}):
            r = self.pause(reason="bekliyor")
        self.assertFalse(r["ok"])
        self.assertEqual(sw.load_projects()["mkt"].phase, "planned")

    def test_refused_without_reason_or_when_running(self):
        with mock.patch.object(sw, "load_card", lambda n, paths=None: {"last_activity": OLD}):
            self.assertFalse(self.pause()["ok"])
            self.live.append(object())
            self.assertFalse(self.pause(reason="x")["ok"])

    def test_idea_and_done_stay_owner_only(self):
        with mock.patch.object(sw, "load_card", lambda n, paths=None: {"last_activity": OLD}):
            for ph in ("idea", "done"):
                self.assertFalse(ws.http_post("/api/steward/project", {"name": "mkt", "phase": ph, "actor": "brain", "reason": "x"})["ok"])


if __name__ == "__main__":
    unittest.main()

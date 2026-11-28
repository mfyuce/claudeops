"""TBD#442 (a), sahip 28 Kas: tur bitmiş, yalnız kabuk/Monitor 30 dk'dan uzun açıksa yönerge/dürtü/cevap teslimi gider;
devir/kapatma/yeniden açma bekler (kabuk öldürülmez). Canlı servis YOK."""
import json
import os
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import bg_work, steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


def _mine():
    with open(f"/proc/{os.getpid()}/stat") as f:
        return f.read().rsplit(")", 1)[1].split()[19]


class RecordShellSince(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name

    def rec(self, status, at_s, sid="s1", fname=None, **extra):
        d = {"pid": os.getpid(), "sessionId": sid, "status": status, "procStart": _mine(), "statusUpdatedAt": at_s * 1000}
        d.update(extra)
        with open(os.path.join(self.dir, fname or f"{os.getpid()}.json"), "w") as f:
            json.dump(d, f)

    def test_shell_older_than_30_min_is_stale(self):
        now = 10_000_000.0
        self.rec("shell", now - 1801)
        self.assertEqual(bg_work.session_record_shell_since(self.dir, "s1"), now - 1801)
        self.assertTrue(bg_work.shell_only_stale(self.dir, "s1", now))

    def test_fresh_shell_busy_idle_or_missing_is_not_stale(self):
        now = 10_000_000.0
        self.rec("shell", now - 1799)
        self.assertFalse(bg_work.shell_only_stale(self.dir, "s1", now))
        for st in ("busy", "idle", "waiting"):
            self.rec(st, now - 9999)
            self.assertFalse(bg_work.shell_only_stale(self.dir, "s1", now), st)
        self.assertFalse(bg_work.shell_only_stale(self.dir, "other", now))
        self.assertFalse(bg_work.shell_only_stale(self.dir, None, now))

    def test_bad_timestamp_is_unknown(self):
        now = 10_000_000.0
        for bad in ("x", None, -5):
            self.rec("shell", 0, statusUpdatedAt=bad)
            self.assertFalse(bg_work.shell_only_stale(self.dir, "s1", now), bad)

    def test_busy_record_of_same_conversation_wins(self):
        now = 10_000_000.0
        self.rec("shell", now - 9999)
        self.rec("busy", now - 10, fname="2.json")      # aynı süreç, ikinci kayıt: birleşik durum busy
        self.assertFalse(bg_work.shell_only_stale(self.dir, "s1", now))


class BlocksMessage(unittest.TestCase):
    def test_rule(self):
        V = sw.SessionView
        self.assertFalse(sw.bg_blocks_message(V(name="a", running=True)))
        self.assertTrue(sw.bg_blocks_message(V(name="a", running=True, subagent_active=True)))
        self.assertFalse(sw.bg_blocks_message(V(name="a", running=True, subagent_active=True, shell_only_stale=True)))
        self.assertTrue(sw.bg_blocks_message(V(name="a", running=True, subagent_unknown=True, shell_only_stale=True)))

    def test_handover_still_defers(self):
        v = sw.SessionView(name="a", running=True, subagent_active=True, shell_only_stale=True)
        cfg = sw.Config()
        cfg.handover_defer_max_minutes = 60
        self.assertEqual(sw.handover_defer_decision(v, cfg, 1000.0, 990.0, None, 0)[0], "defer")
        self.assertTrue(sw.holds_total_slot(v, time.time()))


class DirectiveDefer(unittest.TestCase):
    def _defer(self, stale):
        live = [types.SimpleNamespace(cwd="/x", sid="s1", name="cli", cli="claude")]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(sw, "paths_for", lambda sid: d), \
                mock.patch.object(ws, "_act", lambda *a, **k: {"sessions": [{"name": "cli", "running": True, "busy": False}]}), \
                mock.patch.object(ws.sw, "load_projects", lambda sid: {"cli": sw.Project(name="cli")}), \
                mock.patch.object(ws, "_world", lambda sid: None), \
                mock.patch.object(ws, "_project_for_session", lambda n, p, w: p.get("cli")), \
                mock.patch.object(ws.sw, "load_state", lambda paths: {}), \
                mock.patch.object(ws.sw, "steward_lock", mock.MagicMock()), \
                mock.patch.object(ws.sw, "save_state", lambda *a, **k: None), \
                mock.patch.object(ws.sw, "log_event", lambda *a, **k: None), \
                mock.patch.object(ws, "_live_sessions", lambda name, sid="default": live), \
                mock.patch.object(ws, "long_bg_shells", lambda live: []), \
                mock.patch.object(ws, "_shell_only_stale", lambda cli, sid: stale), \
                mock.patch.object(ws, "subagent_active_for", lambda cwd, sid, now=None, name=None, cli="claude": True):
            return ws._brain_directive_defer("cli", "ucli")

    def test_stale_shell_lets_directive_through(self):
        self.assertIsNone(self._defer(True))
        self.assertEqual(self._defer(False)["code"], "session_busy")


if __name__ == "__main__":
    unittest.main()

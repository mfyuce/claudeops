import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class TestBrainDirectiveSubagentGate(unittest.TestCase):
    """Boşta görünen ama alt ajanı çalışan oturuma beyin direktifi gitmemeli (`cli` 2026-10-24 tekrarı)."""

    def _defer(self, sub, busy=False, shells=()):
        live = [types.SimpleNamespace(cwd="/x", sid="s1", name="cli", cli="claude")]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(sw, "paths_for", lambda sid: d), \
                mock.patch.object(ws, "_act", lambda *a, **k: {"sessions": [{"name": "cli", "running": True, "busy": busy}]}), \
                mock.patch.object(ws.sw, "load_projects", lambda sid: {"cli": sw.Project(name="cli")}), \
                mock.patch.object(ws, "_world", lambda sid: None), \
                mock.patch.object(ws, "_project_for_session", lambda n, p, w: p.get("cli")), \
                mock.patch.object(ws.sw, "load_state", lambda paths: {}), \
                mock.patch.object(ws.sw, "steward_lock", mock.MagicMock()), \
                mock.patch.object(ws.sw, "save_state", lambda *a, **k: None), \
                mock.patch.object(ws.sw, "log_event", lambda *a, **k: None), \
                mock.patch.object(ws, "_live_sessions", lambda name, sid="default": live), \
                mock.patch.object(ws, "long_bg_shells", lambda live: list(shells)), \
                mock.patch.object(ws, "subagent_active_for", lambda cwd, sid, now=None, name=None, cli="claude": sub):
            return ws._brain_directive_defer("cli", "ucli")

    def test_subagent_active_defers(self):
        r = self._defer(True)
        self.assertEqual(r["code"], "session_busy")
        self.assertIn("subagent_active", r["error"])

    def test_idle_without_subagent_sends(self):
        self.assertIsNone(self._defer(False))

    def test_busy_names_long_background_shell(self):
        r = self._defer(False, busy=True, shells=[("cli", "until grep -q load f; do sleep 5; done", 7300.0)])
        self.assertEqual(r["code"], "session_busy")
        self.assertIn("long background shell in cli: 'until grep -q load f; do sleep 5; done' (121 min)", r["error"])

    def test_busy_without_long_shell_keeps_message(self):
        r = self._defer(False, busy=True)
        self.assertTrue(r["error"].endswith("retried on the next tour"))


if __name__ == "__main__":
    unittest.main()

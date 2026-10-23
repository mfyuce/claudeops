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

    def _defer(self, sub):
        live = [types.SimpleNamespace(cwd="/x", sid="s1", name="cli")]
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
                mock.patch.object(ws, "subagent_active_for", lambda cwd, sid, now=None: sub):
            return ws._brain_directive_defer("cli", "ucli")

    def test_subagent_active_defers(self):
        r = self._defer(True)
        self.assertEqual(r["code"], "session_busy")
        self.assertIn("subagent_active", r["error"])

    def test_idle_without_subagent_sends(self):
        self.assertIsNone(self._defer(False))


if __name__ == "__main__":
    unittest.main()

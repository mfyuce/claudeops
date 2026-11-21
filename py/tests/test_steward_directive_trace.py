"""steward log.jsonl `directive` / `directive_deferred` olayları metin özeti (`text_sha1`) ve `delivered` taşır (dalgicppr R8 isteği,
22 Kas). Metin KENDİSİ günlüğe girmez (yalnız sha1 öneki); alansız eski satırlar okuyucuda eskisi gibi sayılır."""
import hashlib
import tempfile
import unittest
from unittest import mock

from claudeops.commands import web_steward as ws
from claudeops import steward as sw


class Trace(unittest.TestCase):
    def test_trace_has_sha1_prefix_and_delivered_flag(self):
        t = ws._directive_trace("merhaba dünya", True)
        self.assertEqual(t, {"text_sha1": hashlib.sha1("merhaba dünya".encode()).hexdigest()[:16], "delivered": True})
        self.assertEqual(ws._directive_trace("x", False)["delivered"], False)

    def test_empty_text_has_no_hash(self):
        self.assertEqual(ws._directive_trace("", False), {"delivered": False})


class DeferLogged(unittest.TestCase):
    def _run(self, text):
        events = []
        live = [mock.MagicMock(cwd="/x", sid="s")]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(sw, "paths_for", lambda sid: d), \
                mock.patch.object(ws, "_act", lambda *a, **k: {"sessions": [{"name": "cli", "running": True, "busy": True}]}), \
                mock.patch.object(ws.sw, "load_projects", lambda sid: {"cli": sw.Project(name="cli")}), \
                mock.patch.object(ws, "_world", lambda sid: None), \
                mock.patch.object(ws, "_project_for_session", lambda n, p, w: p.get("cli")), \
                mock.patch.object(ws.sw, "load_state", lambda paths: {}), \
                mock.patch.object(ws.sw, "steward_lock", mock.MagicMock()), \
                mock.patch.object(ws.sw, "save_state", lambda *a, **k: None), \
                mock.patch.object(ws.sw, "log_event", lambda ev, **k: events.append((ev, k))), \
                mock.patch.object(ws, "_live_sessions", lambda name, sid="default": live), \
                mock.patch.object(ws, "subagent_active_for", lambda cwd, sid, now=None: False):
            ws._brain_directive_defer("cli", "ucli", text)
        return events

    def test_deferred_event_carries_hash_and_not_delivered(self):
        ev = self._run("ertelenen metin")
        self.assertEqual(ev[-1][0], "directive_deferred")
        self.assertEqual(ev[-1][1]["delivered"], False)
        self.assertEqual(ev[-1][1]["text_sha1"], hashlib.sha1("ertelenen metin".encode()).hexdigest()[:16])
        self.assertNotIn("ertelenen metin", str(ev[-1][1]))

    def test_old_call_without_text_still_works(self):
        ev = self._run("")
        self.assertNotIn("text_sha1", ev[-1][1])


if __name__ == "__main__":
    unittest.main()

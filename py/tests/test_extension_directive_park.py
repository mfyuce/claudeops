"""`actor: extension` direktifi (okuma listesi): kapalı oturumu AÇMAZ, paused/done projeyi canlandırmaz; metin TODO.md'ye
`- [ ]` olarak yazılır; drain/kota/panik kapısı extension için de geçer."""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class ExtensionDirectivePark(unittest.TestCase):
    def _run(self, phase="active", live=(), drain=False, existing="# TODO\n"):
        with tempfile.TemporaryDirectory() as d:
            todo = os.path.join(d, "TODO.md")
            open(todo, "w", encoding="utf-8").write(existing)
            proj = sw.Project(name="okp", phase=phase)
            give = mock.MagicMock(return_value={"ok": True, "name": "okp"})
            with mock.patch.object(ws.sw, "load_projects", lambda sid: {"okp": proj}), \
                    mock.patch.object(ws, "_world", lambda sid: None), \
                    mock.patch.object(ws, "_project_for_session", lambda n, p, w: p.get("okp")), \
                    mock.patch.object(ws, "_gate", lambda *a, **k: None), \
                    mock.patch.object(ws, "_upper_model_gate", lambda *a, **k: None), \
                    mock.patch.object(ws, "_live_sessions", lambda n, sid="default": list(live)), \
                    mock.patch.object(ws, "_cwd_resolver", lambda: (lambda n: d)), \
                    mock.patch.object(ws, "_doc_path", lambda cwd, f: todo), \
                    mock.patch.object(ws, "quota_blocking", lambda: False), \
                    mock.patch.object(ws.sw, "panic_active", lambda: False), \
                    mock.patch.object(ws.sw, "log_event", lambda *a, **k: None), \
                    mock.patch.object(ws, "steward_config", lambda sid="default": types.SimpleNamespace(drain=drain, lang="tr")), \
                    mock.patch.object(ws, "_no_work_directive_reopen", lambda *a, **k: None), \
                    mock.patch.object(ws, "_give_directive", give):
                r = ws.http_directive({"name": "okp", "text": "oku\nşunu", "actor": "extension"})
            return r, give, open(todo, encoding="utf-8").read()

    def test_closed_session_writes_todo_and_does_not_open(self):
        r, give, body = self._run()
        self.assertEqual(r.get("parked"), "todo")
        give.assert_not_called()
        self.assertIn("- [ ] (uzantı direktifi, oturum kapalıydı) oku şunu\n", body)

    def test_paused_project_not_revived_even_if_session_live(self):
        r, give, body = self._run(phase="paused", live=[object()])
        self.assertEqual(r.get("parked"), "todo")
        give.assert_not_called()

    def test_live_active_session_goes_through(self):
        r, give, body = self._run(live=[object()])
        self.assertNotIn("parked", r)
        give.assert_called_once()
        self.assertRegex(body, r"- \[ \] \(\d{4}-\d\d-\d\d, direktif [0-9a-f]{12}\) oku şunu\n")     # 20 Kas: her direktif TODO'ya yazılır

    def test_drain_blocks_extension(self):
        r, give, body = self._run(drain=True, live=[object()])
        self.assertEqual(r.get("code"), "draining")
        give.assert_not_called()

    def test_repeated_note_not_duplicated(self):
        _, _, body = self._run(existing="# TODO\n- [ ] (uzantı direktifi, oturum kapalıydı) oku şunu\n")
        self.assertEqual(body.count("oku şunu"), 1)


if __name__ == "__main__":
    unittest.main()

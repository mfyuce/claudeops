"""review R-3: `http_restart` beyin direktifinin reddedilme koşullarını DURDURMADAN önce denetler (reddedilen restart oturumu kapalı bırakmasın)."""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class RestartPrecheckTest(unittest.TestCase):
    def test_non_brain_actor_has_no_block(self):
        self.assertIsNone(ws._brain_directive_blocks("p", {"actor": "human"}, "default"))
        self.assertIsNone(ws._brain_directive_blocks("p", {}, "default"))

    def test_blocked_brain_restart_never_stops(self):
        blocked = {"ok": False, "code": "owner_pending", "error": "x"}
        with mock.patch.object(ws, "_gate", return_value=None), mock.patch.object(ws, "_upper_model_gate", return_value=None), \
                mock.patch.object(ws, "_brain_directive_blocks", return_value=blocked), \
                mock.patch.object(ws, "_act") as act, mock.patch.object(ws, "_remote_stop_and_wait") as rstop:
            res = ws.http_restart({"name": "proj", "actor": "brain"}, "default")
        self.assertEqual(res, blocked)
        act.assert_not_called()
        rstop.assert_not_called()

    def test_drain_blocks_brain_only(self):
        cfg = mock.Mock(drain=True)
        with mock.patch.object(ws, "steward_config", return_value=cfg):
            r = ws._brain_directive_blocks("p", {"actor": "brain"}, "default")
            self.assertEqual(r["code"], "draining")
            self.assertIsNone(ws._brain_directive_blocks("p", {"actor": "human"}, "default"))


class RestartOpenDialogTest(unittest.TestCase):
    """Açık soru/izin diyaloğundaki oturum restart ile durdurulmaz; yalnız insanın `force`u geçer."""
    def run_restart(self, status="waiting", **data):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "4242.json"), "w") as f:
                json.dump({"pid": 4242, "status": status, "waitingFor": "input needed"}, f)
            proc = SimpleNamespace(name="proj", pid=4242, cli="claude", cwd=d, sid="s")
            with mock.patch.object(ws.paths_mod, "SESSIONS_DIR", d), mock.patch.object(ws, "_gate", return_value=None), \
                    mock.patch.object(ws, "_upper_model_gate", return_value=None), \
                    mock.patch.object(ws, "_brain_directive_blocks", return_value=None), \
                    mock.patch.object(ws, "_name_host", return_value=""), mock.patch.object(ws, "steward_config", return_value=ws.sw.Config()), \
                    mock.patch.object(ws, "_live_sessions", return_value=[proc]), mock.patch.object(ws.sw, "log_event"), \
                    mock.patch.object(ws, "_act", return_value={"ok": True}) as act, \
                    mock.patch.object(ws, "http_directive", return_value={"ok": True}) as directive:
                res = ws.http_restart(dict(data, name="proj"), "default")
            return res, act.call_count, directive.call_count

    def test_open_dialog_is_never_stopped_without_force(self):
        for data in ({"actor": "brain"}, {}, {"actor": "brain", "force": True}):
            with self.subTest(data=data):
                res, stops, sent = self.run_restart(**data)
                self.assertEqual((res["ok"], res.get("code"), stops, sent), (False, "question_open", 0, 0))

    def test_owner_force_restarts(self):
        res, stops, sent = self.run_restart(actor="cli", force=True)
        self.assertEqual((res["ok"], stops, sent), (True, 1, 1))

    def test_idle_session_restarts(self):
        res, stops, sent = self.run_restart(status="idle", actor="brain")
        self.assertEqual((res["ok"], stops, sent), (True, 1, 1))


if __name__ == "__main__":
    unittest.main()

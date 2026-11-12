"""review R-3: `http_restart` beyin direktifinin reddedilme koşullarını DURDURMADAN önce denetler (reddedilen restart oturumu kapalı bırakmasın)."""
import os
import sys
import unittest
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


if __name__ == "__main__":
    unittest.main()

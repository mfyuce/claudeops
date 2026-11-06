"""Panel Durdur ho kuralı: human_stop_with_ho yalnız act + kayıtlı yerel proje oturumunda devreye girer (stdlib unittest)."""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_steward as ws  # noqa: E402


def _cfg(enabled=True, mode="act"):
    return types.SimpleNamespace(enabled=enabled, mode=mode, brain_name="degnekci")


class HumanStopHoTest(unittest.TestCase):
    def run_it(self, cfg, host="", real="p1", proj=object()):
        with mock.patch.object(ws, "steward_config", return_value=cfg), \
             mock.patch.object(ws, "_name_host", return_value=host), \
             mock.patch.object(ws, "_resolved_local_name", return_value=real), \
             mock.patch.object(ws.sw, "load_projects", return_value={}), \
             mock.patch.object(ws, "_world", return_value=None), \
             mock.patch.object(ws, "_project_for_session", return_value=proj), \
             mock.patch.object(ws, "http_stop", return_value={"ok": True, "note": "ho"}) as hs:
            return ws.human_stop_with_ho("p1"), hs

    def test_act_registered_goes_through_ho(self):
        r, hs = self.run_it(_cfg())
        self.assertEqual(r["note"], "ho")
        self.assertEqual(hs.call_args[0][0]["actor"], "human")

    def test_off_or_observe_falls_through(self):
        self.assertIsNone(self.run_it(_cfg(enabled=False))[0])
        self.assertIsNone(self.run_it(_cfg(mode="observe"))[0])

    def test_remote_unregistered_brain_fall_through(self):
        self.assertIsNone(self.run_it(_cfg(), host="yuhem")[0])
        self.assertIsNone(self.run_it(_cfg(), proj=None)[0])
        self.assertIsNone(self.run_it(_cfg(), real="degnekci")[0])


if __name__ == "__main__":
    unittest.main()

"""`cops kill` ho kuralı: varsayılan panel /api/stop; --force ya da panel yok -> doğrudan (stdlib unittest)."""
import argparse
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import kill as k  # noqa: E402


def args(**kw):
    d = dict(names=["p1"], grace=1.0, dry_run=False, force=False, port=8765)
    d.update(kw)
    return argparse.Namespace(**d)


class KillHoTest(unittest.TestCase):
    def setUp(self):
        self.s = types.SimpleNamespace(pid=999, name="p1")
        for p in (mock.patch.object(k, "find_by_name", return_value=[self.s]),
                  mock.patch.object(k, "kill_session_and_parent", return_value="ok")):
            m = p.start()
            self.addCleanup(p.stop)
            if p.attribute == "kill_session_and_parent":
                self.kill = m

    def test_panel_ok_no_direct_kill(self):
        with mock.patch.object(k.mcp_queue, "_api", return_value={"ok": True, "note": "devir gönderildi"}):
            self.assertEqual(k.run(args()), 0)
        self.kill.assert_not_called()

    def test_panel_error_counts_no_direct_kill(self):
        with mock.patch.object(k.mcp_queue, "_api", return_value={"ok": False, "error": "not running"}):
            self.assertEqual(k.run(args()), 1)
        self.kill.assert_not_called()

    def test_panel_down_falls_back(self):
        with mock.patch.object(k.mcp_queue, "_api", side_effect=k.mcp_queue.ApiError("cannot reach claudeops panel")):
            self.assertEqual(k.run(args()), 0)
        self.kill.assert_called_once()

    def test_force_skips_panel(self):
        with mock.patch.object(k.mcp_queue, "_api") as api:
            k.run(args(force=True))
        api.assert_not_called()
        self.kill.assert_called_once()

    def test_dry_run_skips_panel_and_kill(self):
        with mock.patch.object(k.mcp_queue, "_api") as api:
            k.run(args(dry_run=True))
        api.assert_not_called()
        self.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()

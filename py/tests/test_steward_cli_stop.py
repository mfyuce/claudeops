"""cmd_stop: /api/steward/stop'a actor=cli ile POST eder; ok değilse 1 döner (_api sahte; ağ YOK)."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import steward as st  # noqa: E402


class CmdStopTest(unittest.TestCase):
    def _run(self, res, **kw):
        calls = []

        def fake(port, method, path, body=None, sid="default"):
            calls.append((method, path, body, sid))
            return res

        args = SimpleNamespace(name="cli2", reason=kw.get("reason", ""), port=1, sid="default")
        with mock.patch.object(st, "_api", fake), mock.patch("builtins.print"):
            rc = st.cmd_stop(args)
        return rc, calls

    def test_posts_stop_with_actor_cli(self):
        rc, calls = self._run({"ok": True}, reason="bitti")
        self.assertEqual(rc, 0)
        m, path, body, _ = calls[0]
        self.assertEqual((m, path), ("POST", "/api/steward/stop"))
        self.assertEqual(body, {"name": "cli2", "actor": "cli", "reason": "bitti"})

    def test_failure_returns_1(self):
        rc, _ = self._run({"ok": False, "error": "x"})
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()

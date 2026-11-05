"""PROC-03: CLI'si cikmis, `exec bash`le canli kalan tmux oturumu spawn'dan once kapatilir. Gercek tmux/psutil YOK.
Calistirma: python3 -m unittest discover -s py/tests"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import spawn, tmux_backend as tb  # noqa: E402

NOW = 1_000_000.0


def _run(stdout, rc=0):
    return lambda *a, **k: SimpleNamespace(returncode=rc, stdout=stdout)


class GhostDetectTest(unittest.TestCase):
    def _ghost(self, stdout, rc=0, childless=True):
        with mock.patch.object(tb.subprocess, "run", _run(stdout, rc)), \
                mock.patch.object(tb, "_pid_childless", lambda pid: childless):
            return tb.tmux_ghost_session("p", now=NOW)

    def test_old_bare_bash_is_ghost(self):
        self.assertTrue(self._ghost(f"bash\t{NOW - 100:.0f}\t42\n"))

    def test_live_cli_is_not_ghost(self):
        self.assertFalse(self._ghost(f"claude\t{NOW - 100:.0f}\t42\n"))

    def test_young_session_is_not_ghost(self):
        self.assertFalse(self._ghost(f"bash\t{NOW - 5:.0f}\t42\n"))

    def test_bash_with_child_is_not_ghost(self):
        self.assertFalse(self._ghost(f"bash\t{NOW - 100:.0f}\t42\n", childless=False))

    def test_no_session_or_garbage(self):
        self.assertFalse(self._ghost("", rc=1))
        self.assertFalse(self._ghost("bash\n"))
        self.assertFalse(self._ghost("bash\tx\t42\n"))

    def test_mixed_panes(self):
        self.assertFalse(self._ghost(f"bash\t{NOW - 100:.0f}\t42\nnode\t{NOW - 100:.0f}\t43\n"))


class ReclaimTest(unittest.TestCase):
    def _reclaim(self, cli="claude", ghost=True):
        killed, logs = [], []
        with mock.patch.object(spawn, "tmux_available", lambda: True), \
                mock.patch.object(tb, "tmux_ghost_session", lambda n: ghost), \
                mock.patch.object(tb, "tmux_capture", lambda n, lines=2000: "Out of credits\n$ "), \
                mock.patch.object(tb, "tmux_kill_session", killed.append), \
                mock.patch.object(spawn, "diag_log", lambda ev, **k: logs.append((ev, k))):
            spawn._reclaim_ghost_session("p", cli)
        return killed, logs

    def test_ghost_killed_and_tail_logged(self):
        killed, logs = self._reclaim()
        self.assertEqual(killed, ["p"])
        self.assertEqual(logs[0][0], "spawn_ghost_reclaimed")
        self.assertIn("Out of credits", logs[0][1]["tail"])

    def test_shell_provider_untouched(self):
        self.assertEqual(self._reclaim(cli="shell"), ([], []))

    def test_not_ghost_untouched(self):
        self.assertEqual(self._reclaim(ghost=False), ([], []))

    def test_error_never_raises(self):
        with mock.patch.object(spawn, "tmux_available", lambda: True), \
                mock.patch.object(tb, "tmux_ghost_session", mock.Mock(side_effect=RuntimeError("x"))), \
                mock.patch.object(spawn, "diag_log", lambda *a, **k: None):
            spawn._reclaim_ghost_session("p", "claude")


if __name__ == "__main__":
    unittest.main()

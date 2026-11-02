"""kill_session_and_parent: psutil.AccessDenied temizliği yarıda bırakmaz (tmux kill-session + dış pencere yine çalışır)."""
import os
import sys
import unittest
from unittest import mock

import psutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import kill, tmux_backend  # noqa: E402


class _Outer:
    def __init__(self):
        self.killed = False

    def create_time(self):
        return 5.0

    def kill(self):
        self.killed = True


class _Main:
    def create_time(self):
        return 1.0


class KillAccessDeniedTests(unittest.TestCase):
    def test_access_denied_still_cleans_up(self):
        outer = _Outer()
        cleaned = []

        def fake_process(pid):
            return outer if pid == 777 else _Main()

        def denied(*a, **k):
            raise psutil.AccessDenied(1234)

        with mock.patch.object(kill.psutil, "Process", fake_process), \
                mock.patch.object(kill, "kill_session", denied), \
                mock.patch.object(tmux_backend, "is_tmux_backed", lambda pid: True), \
                mock.patch.object(tmux_backend, "find_outer_bash_pids", lambda name: [(777, 5.0)]), \
                mock.patch.object(tmux_backend, "tmux_kill_session", lambda name: cleaned.append(name)):
            with self.assertRaises(psutil.AccessDenied):
                kill.kill_session_and_parent(1234, grace=0.1, name="foo")
        self.assertEqual(cleaned, ["foo"])
        self.assertTrue(outer.killed)


if __name__ == "__main__":
    unittest.main()

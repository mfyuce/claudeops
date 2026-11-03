"""kill_session: create_time uyuşmazsa (PID yeniden kullanımı) sinyal gönderilmez."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import kill  # noqa: E402


class _Proc:
    def __init__(self, ct):
        self._ct = ct
        self.signals = []

    def create_time(self):
        return self._ct

    def send_signal(self, sig):
        self.signals.append(sig)

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.signals.append("KILL")


class KillCreateTimeTest(unittest.TestCase):
    def _run(self, **kw):
        p = _Proc(100.0)
        with mock.patch.object(kill.psutil, "Process", lambda pid: p):
            res = kill.kill_session(1234, grace=0.1, **kw)
        return res, p

    def test_mismatched_create_time_skips_signal(self):
        res, p = self._run(create_time=999.0)
        self.assertEqual(res, "already_dead")
        self.assertEqual(p.signals, [])

    def test_matching_create_time_signals(self):
        res, p = self._run(create_time=100.0)
        self.assertEqual(res, "clean")
        self.assertEqual(len(p.signals), 1)

    def test_no_create_time_is_legacy(self):
        res, _p = self._run()
        self.assertEqual(res, "clean")


if __name__ == "__main__":
    unittest.main()

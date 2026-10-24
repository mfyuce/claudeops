"""remote_desktop: devralınan (adopt) orphan PID'i yeniden doğrulanır (stdlib unittest).

Çalıştırma:  python3 py/tests/test_remote_desktop_adopt.py -v
Gerçek süreç öldürülmez: `os.kill`, `_pid_alive`, `_is_screenshare`, `_port_open` sahte.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import remote_desktop as rd  # noqa: E402


class AdoptRevalidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pidfile = os.path.join(self.tmp, "rd.pid")
        for p in (mock.patch.object(rd, "PID_FILE", self.pidfile), mock.patch.object(rd, "_proc", None),
                  mock.patch.object(rd, "_port", None), mock.patch.object(rd, "_adopted_pid", None)):
            p.start()
            self.addCleanup(p.stop)

    def write(self, pid=4242, port=8123):
        with open(self.pidfile, "w") as f:
            f.write(f"{pid} {port}\n")

    def test_alive_screenshare_with_open_port_is_adopted(self):
        self.write()
        with mock.patch.object(rd, "_pid_alive", return_value=True), mock.patch.object(rd, "_is_screenshare", return_value=True), \
             mock.patch.object(rd, "_port_open", return_value=True):
            self.assertEqual(rd.status(), {"running": True, "port": 8123})

    def test_reused_pid_is_not_adopted(self):
        self.write()
        with mock.patch.object(rd, "_pid_alive", return_value=True), mock.patch.object(rd, "_is_screenshare", return_value=False), \
             mock.patch.object(rd, "_port_open", return_value=True):
            self.assertEqual(rd.status(), {"running": False, "port": None})
        self.assertFalse(os.path.exists(self.pidfile))

    def test_adopted_orphan_that_dies_is_dropped_on_next_status(self):
        self.write()
        with mock.patch.object(rd, "_pid_alive", return_value=True), mock.patch.object(rd, "_is_screenshare", return_value=True), \
             mock.patch.object(rd, "_port_open", return_value=True):
            self.assertTrue(rd.status()["running"])
        with mock.patch.object(rd, "_pid_alive", return_value=False):
            self.assertEqual(rd.status(), {"running": False, "port": None})
        self.assertIsNone(rd.current_port())

    def test_stop_never_signals_a_reused_pid(self):
        self.write()
        with mock.patch.object(rd, "_pid_alive", return_value=True), mock.patch.object(rd, "_is_screenshare", return_value=True), \
             mock.patch.object(rd, "_port_open", return_value=True):
            rd.status()                                    # adopt
        with mock.patch.object(rd, "_pid_alive", return_value=True), mock.patch.object(rd, "_is_screenshare", return_value=False), \
             mock.patch.object(rd.os, "kill") as kill:
            self.assertTrue(rd.stop()["ok"])
        kill.assert_not_called()

    def test_is_screenshare_reads_cmdline(self):
        self.assertFalse(rd._is_screenshare(2 ** 22 + 12345))        # var olmayan PID
        self.assertFalse(rd._is_screenshare(os.getpid()))             # python süreci screenshare değil


if __name__ == "__main__":
    unittest.main()

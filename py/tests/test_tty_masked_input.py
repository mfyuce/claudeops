"""pane_is_masked_input / tty_is_masked: ICANON açık + ECHO kapalı = parola istemi (ECHO tek başına yetmez). tmux'a DOKUNMAZ (pty + mock)."""
import os
import pty
import subprocess
import sys
import termios
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import tmux_backend  # noqa: E402


def _set_lflag(fd, icanon, echo):
    attrs = termios.tcgetattr(fd)
    lf = attrs[3]
    lf = (lf | termios.ICANON) if icanon else (lf & ~termios.ICANON)
    lf = (lf | termios.ECHO) if echo else (lf & ~termios.ECHO)
    attrs[3] = lf
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


class TtyMaskedTest(unittest.TestCase):
    def _case(self, icanon, echo):
        master, slave = pty.openpty()
        try:
            _set_lflag(slave, icanon, echo)
            return tmux_backend.tty_is_masked(os.ttyname(slave))
        finally:
            os.close(master)
            os.close(slave)

    def test_icanon_without_echo_is_masked(self):
        self.assertIs(self._case(True, False), True)

    def test_raw_no_echo_shell_is_not_masked(self):
        self.assertIs(self._case(False, False), False)

    def test_normal_echo_is_not_masked(self):
        self.assertIs(self._case(True, True), False)

    def test_empty_or_bad_path_is_none(self):
        self.assertIsNone(tmux_backend.tty_is_masked(""))
        self.assertIsNone(tmux_backend.tty_is_masked("/nonexistent/pty"))

    def test_pane_is_masked_input_uses_pane_tty(self):
        cp = subprocess.CompletedProcess([], 0, stdout="/dev/pts/x\n", stderr="")
        with mock.patch.object(tmux_backend.subprocess, "run", return_value=cp), \
             mock.patch.object(tmux_backend, "tty_is_masked", return_value=True) as m:
            self.assertIs(tmux_backend.pane_is_masked_input("s"), True)
        m.assert_called_once_with("/dev/pts/x")

    def test_pane_is_masked_input_tmux_failure_is_none(self):
        cp = subprocess.CompletedProcess([], 1, stdout="", stderr="no")
        with mock.patch.object(tmux_backend.subprocess, "run", return_value=cp):
            self.assertIsNone(tmux_backend.pane_is_masked_input("s"))


if __name__ == "__main__":
    unittest.main()

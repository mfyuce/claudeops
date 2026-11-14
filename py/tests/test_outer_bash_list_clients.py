"""TBD#26: find_outer_bash_pids önce tmux list-clients, boşsa psutil taraması.

Çalıştırma:  python3 py/tests/test_outer_bash_list_clients.py -v
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import tmux_backend as tb  # noqa: E402


def _proc(pid, name, cmdline, parent=None, ct=1.0):
    return SimpleNamespace(pid=pid, info={"pid": pid, "name": name}, name=lambda: name,
                           cmdline=lambda: cmdline, create_time=lambda: ct, parent=lambda: parent)


class ListClientsTests(unittest.TestCase):
    def test_client_parent_bash_found(self):
        bash = _proc(10, "bash", ["bash", "-c", "tmux ...; exec bash"], ct=5.0)
        client = _proc(11, "tmux: client", ["tmux"], parent=bash)
        run = SimpleNamespace(returncode=0, stdout="11\n")
        with mock.patch.object(tb.subprocess, "run", return_value=run), \
             mock.patch("psutil.Process", return_value=client):
            self.assertEqual(tb._outer_bash_via_list_clients("n"), [(10, 5.0)])

    def test_failure_returns_empty(self):
        with mock.patch.object(tb.subprocess, "run", side_effect=OSError):
            self.assertEqual(tb._outer_bash_via_list_clients("n"), [])
        run = SimpleNamespace(returncode=1, stdout="")
        with mock.patch.object(tb.subprocess, "run", return_value=run):
            self.assertEqual(tb._outer_bash_via_list_clients("n"), [])

    def test_find_uses_native_first_then_falls_back(self):
        with mock.patch.object(tb, "_outer_bash_via_list_clients", return_value=[(1, 2.0)]):
            self.assertEqual(tb.find_outer_bash_pids("n"), [(1, 2.0)])
        scan = _proc(7, "bash", ["bash", "-c", "tmux -L cops new-session -A -s n -c /x; exec bash"], ct=3.0)
        with mock.patch.object(tb, "_outer_bash_via_list_clients", return_value=[]), \
             mock.patch("psutil.process_iter", return_value=[scan]):
            self.assertEqual(tb.find_outer_bash_pids("n"), [(7, 3.0)])

    def test_fallback_matches_open_window_exact_target(self):
        """open_window() penceresi `attach-session -t =NAME` (tmux_attach_shell_fragment) ile açılır: yedek tarama onu da bulmalı."""
        frag = tb.tmux_attach_shell_fragment("n")
        scan = _proc(9, "bash", ["bash", "-c", frag + "; exec bash"], ct=4.0)
        with mock.patch.object(tb, "_outer_bash_via_list_clients", return_value=[]), \
             mock.patch("psutil.process_iter", return_value=[scan]):
            self.assertEqual(tb.find_outer_bash_pids("n"), [(9, 4.0)])


if __name__ == "__main__":
    unittest.main()

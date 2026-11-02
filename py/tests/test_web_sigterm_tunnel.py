"""SIGTERM handler `os._exit` ettiği için cloudflared tünelini önce sonlandırmalı (stdlib unittest, süreç taklit).

Çalıştırma:  python3 py/tests/test_web_sigterm_tunnel.py -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402


class SigtermTunnelTest(unittest.TestCase):
    def tearDown(self):
        web._TUNNEL_PROC = None

    def test_terminate_tunnel_without_proc_is_noop(self):
        web._TUNNEL_PROC = None
        web._terminate_tunnel()

    def test_terminate_tunnel_swallows_errors(self):
        proc = mock.Mock()
        proc.terminate.side_effect = OSError("gone")
        web._TUNNEL_PROC = proc
        web._terminate_tunnel()
        proc.terminate.assert_called_once()

    def test_sigterm_handler_terminates_tunnel_before_exit(self):
        order = []
        proc = mock.Mock()
        proc.terminate.side_effect = lambda: order.append("terminate")
        web._TUNNEL_PROC = proc
        with mock.patch.object(web, "diag_log"), \
                mock.patch.object(web, "_save_closing_snapshot"), \
                mock.patch.object(web.os, "_exit", side_effect=lambda c: order.append("exit")):
            web._sigterm_handler(15, None)
        self.assertEqual(order, ["terminate", "exit"])


if __name__ == "__main__":
    unittest.main()

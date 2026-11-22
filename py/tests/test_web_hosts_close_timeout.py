"""web_hosts: uzak WS kapanışı varsayılan 10 sn close_timeout'a takılmasın (TODO 1175). Ağ yok."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_hosts  # noqa: E402


class CloseTimeoutTest(unittest.TestCase):
    def test_default_close_timeout_is_short(self):
        with mock.patch.object(web_hosts, "ws_connect") as m:
            web_hosts._guarded_ws_connect("ws://10.1.2.3:1/ws", open_timeout=1.0)
        self.assertEqual(m.call_args.kwargs["close_timeout"], 1.5)

    def test_explicit_close_timeout_wins(self):
        with mock.patch.object(web_hosts, "ws_connect") as m:
            web_hosts._guarded_ws_connect("ws://10.1.2.3:1/ws", open_timeout=1.0, close_timeout=0.5)
        self.assertEqual(m.call_args.kwargs["close_timeout"], 0.5)


if __name__ == "__main__":
    unittest.main()

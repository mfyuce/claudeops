import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ws_ticket  # noqa: E402


class WsTicket(unittest.TestCase):
    def setUp(self):
        ws_ticket._TICKETS.clear()

    def test_single_use(self):
        t = ws_ticket.issue(now=100.0)
        self.assertTrue(ws_ticket.consume(t, now=101.0))
        self.assertFalse(ws_ticket.consume(t, now=101.0))

    def test_expires(self):
        t = ws_ticket.issue(now=100.0)
        self.assertFalse(ws_ticket.consume(t, now=100.0 + ws_ticket.TTL_SECONDS + 0.1))

    def test_unknown_and_empty(self):
        self.assertFalse(ws_ticket.consume("nope"))
        self.assertFalse(ws_ticket.consume(""))

    def test_cap_drops_oldest(self):
        first = ws_ticket.issue(now=1.0)
        for i in range(ws_ticket.MAX_PENDING):
            ws_ticket.issue(now=2.0 + i * 0.001)
        self.assertLessEqual(len(ws_ticket._TICKETS), ws_ticket.MAX_PENDING)
        self.assertFalse(ws_ticket.consume(first, now=3.0))


class HandlerWiring(unittest.TestCase):
    def _h(self, path, token="tok"):
        from claudeops.commands import web
        h = web._Handler.__new__(web._Handler)
        h.path = path
        h.token = token
        h.headers = {}
        return h

    def test_ws_accepts_ticket_once_and_legacy_token(self):
        ws_ticket._TICKETS.clear()
        t = ws_ticket.issue()
        h = self._h("/ws?ticket=" + t)
        self.assertTrue(h._authorized_ws())
        self.assertFalse(h._authorized_ws())             # ikinci kullanım
        self.assertTrue(self._h("/ws?token=tok")._authorized_ws())   # geriye uyum
        self.assertFalse(self._h("/ws?token=bad")._authorized_ws())

    def test_ticket_does_not_authorize_rest(self):
        t = ws_ticket.issue()
        self.assertFalse(self._h("/api/status?ticket=" + t)._authorized())


if __name__ == "__main__":
    unittest.main()

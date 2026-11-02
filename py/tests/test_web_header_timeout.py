"""TBD#54: başlık okuma fazında 15 sn soket timeout, başlık okununca eski değere dönüş.

Çalıştırma:  python3 py/tests/test_web_header_timeout.py -v
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402


class _Conn:
    def __init__(self):
        self.t = None
        self.history = []

    def gettimeout(self):
        return self.t

    def settimeout(self, v):
        self.t = v
        self.history.append(v)


class HeaderTimeoutTests(unittest.TestCase):
    def _handler(self, raw: bytes, conn):
        h = web._Handler.__new__(web._Handler)
        h.connection = conn
        h.rfile = io.BytesIO(raw)
        h.wfile = io.BytesIO()
        h.client_address = ("127.0.0.1", 1)
        h.server = type("S", (), {})()
        h.requestline = ""
        h.request_version = "HTTP/1.1"
        h.command = None
        h.close_connection = True
        return h

    def test_timeout_set_during_headers_and_restored(self):
        conn = _Conn()
        conn.t = 99.0
        h = self._handler(b"GET /x HTTP/1.1\r\nHost: a\r\n\r\n", conn)
        h.raw_requestline = h.rfile.readline()
        h._body_timeout = 99.0
        self.assertTrue(h.parse_request())
        self.assertEqual(conn.t, 99.0)          # parse_request sonrası eski değer

    def test_constant_is_15(self):
        self.assertEqual(web._Handler.HEADER_READ_TIMEOUT, 15.0)


if __name__ == "__main__":
    unittest.main()

"""Gövdesi okunmadan reddedilen istek keep-alive bağlantısını kirletmez (canlı 25 Kas: 404 sonrası `bad response (not JSON)`).

Çalıştırma:  python3 py/tests/test_web_unread_body.py -v
"""
import json
import os
import socket
import sys
import threading
import unittest
from http.client import HTTPResponse
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402

TOKEN = "t0k"


class _H(web._Handler):
    token = TOKEN
    DRAIN_TIMEOUT = 0.5


def _req(path, body=b'{"host": "x"}', token=TOKEN, extra=b"", length=None):
    n = len(body) if length is None else length
    return (b"POST %s?token=%s HTTP/1.1\r\nHost: a\r\nContent-Type: application/json\r\n%sContent-Length: %d\r\n\r\n"
            % (path.encode(), token.encode(), extra, n)) + body


class UnreadBodyTests(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.sock = socket.create_connection(self.srv.server_address, timeout=10)
        self.addCleanup(self.sock.close)

    def _exchange(self, raw):
        self.sock.sendall(raw)
        r = HTTPResponse(self.sock, method="POST")
        r.begin()
        return r, r.read()

    def _assert_next_request_clean(self):
        # ikinci istek AYNI soketten: kirlenmişse stdlib HTML 400/501 döner
        r, body = self._exchange(_req("/api/yok-boyle-uc"))
        self.assertEqual(r.status, 404)
        self.assertEqual(json.loads(body), {"error": "not found"})

    def test_404_then_valid_request_on_same_socket(self):
        r, _ = self._exchange(_req("/api/yok-boyle-uc"))
        self.assertEqual(r.status, 404)
        self.assertIsNone(r.getheader("Connection"))
        self._assert_next_request_clean()

    def test_401_then_valid_request_on_same_socket(self):
        r, _ = self._exchange(_req("/api/settings", token="yanlis"))
        self.assertEqual(r.status, 401)
        self._assert_next_request_clean()

    def test_pipelined_requests(self):
        self.sock.sendall(_req("/api/yok-1") + _req("/api/yok-2"))
        for _ in range(2):
            r = HTTPResponse(self.sock, method="POST")
            r.fp.close()
            r.fp = self.sock.makefile("rb", buffering=0)       # tamponsuz: ikinci yanıtın baytı yutulmasın
            r.begin()
            self.assertEqual(r.status, 404)
            r.read()

    def test_oversized_unread_body_closes_connection(self):
        r, _ = self._exchange(_req("/api/yok", body=b"x", length=_H.DRAIN_MAX_BYTES + 1))
        self.assertEqual(r.status, 404)
        self.assertEqual(r.getheader("Connection"), "close")

    def test_slow_body_closes_connection(self):
        r, _ = self._exchange(_req("/api/yok", body=b"x", length=100))
        self.assertEqual(r.status, 404)
        self.assertEqual(r.getheader("Connection"), "close")

    def test_chunked_closes_connection(self):
        r, _ = self._exchange(_req("/api/yok", body=b"", extra=b"Transfer-Encoding: chunked\r\n"))
        self.assertEqual(r.getheader("Connection"), "close")


if __name__ == "__main__":
    unittest.main()

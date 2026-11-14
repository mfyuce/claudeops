"""POST gövde okuma zaman aşımı (sahip 14 Kas, TBD a): yavaş/eksik gövde 408 + bağlantı kapanır; WS/boşta bağlantı zaman aşımı değişmez."""
import io
import socket
import unittest
from unittest import mock

from claudeops.commands import web


class FakeConn:
    def __init__(self):
        self.t = None
        self.calls = []

    def gettimeout(self):
        return self.t

    def settimeout(self, v):
        self.calls.append(v)
        self.t = v


def handler(rfile):
    h = web._Handler.__new__(web._Handler)
    h.connection = FakeConn()
    h.rfile = rfile
    h.close_connection = False
    return h


class SlowFile:
    def read(self, n):
        raise socket.timeout("timed out")


class BodyTimeout(unittest.TestCase):
    def test_read_ok_restores_previous_timeout(self):
        h = handler(io.BytesIO(b"abcd"))
        h.connection.t = None                            # WS/tünel gibi sınırsız bağlantı
        self.assertEqual(h._read_body(4), b"abcd")
        self.assertEqual(h.connection.calls, [web._Handler.BODY_READ_TIMEOUT, None])
        self.assertIsNone(h.connection.t)                # önceki (sınırsız) değer geri geldi

    def test_slow_body_raises(self):
        h = handler(SlowFile())
        with self.assertRaises(web._BodyTimeout):
            h._read_body(10)
        self.assertIsNone(h.connection.t)

    def test_short_body_raises(self):
        with self.assertRaises(web._BodyTimeout):
            handler(io.BytesIO(b"ab"))._read_body(10)

    def test_do_post_maps_to_408_and_closes(self):
        h = handler(io.BytesIO(b""))
        sent = []
        h._json = lambda body, status=200: sent.append((status, body))
        with mock.patch.object(h, "_do_post_inner", side_effect=web._BodyTimeout("x")):
            h.do_POST()
        self.assertEqual(sent[0][0], 408)
        self.assertTrue(h.close_connection)

    def test_real_socket_slow_body_gets_408(self):
        import http.server, threading, time
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        srv.daemon_threads = True
        web._Handler.token = "t"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        with mock.patch.object(web._Handler, "BODY_READ_TIMEOUT", 0.5):
            c = socket.create_connection(srv.server_address, timeout=5)
            self.addCleanup(c.close)
            c.sendall(b"POST /q/abc HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\nContent-Type: application/x-www-form-urlencoded\r\n\r\nanswer=")
            t0 = time.monotonic()
            data = b""
            while True:                             # gövde eksik kalır: sunucu 408 yanıtlar ve bağlantıyı KAPATIR (EOF)
                chunk = c.recv(4096)
                if not chunk:
                    break
                data += chunk
            self.assertIn(b" 408 ", data.split(b"\r\n")[0])
            self.assertLess(time.monotonic() - t0, 4)


if __name__ == "__main__":
    unittest.main()


class AuthFailClosed(unittest.TestCase):
    def test_empty_server_token_never_authorizes(self):
        h = handler(io.BytesIO(b""))
        h.token = ""
        h.path = "/api/status"
        h.headers = {}
        self.assertFalse(h._authorized())
        h.path = "/api/status?token="
        self.assertFalse(h._authorized())

    def test_valid_token_still_ok(self):
        h = handler(io.BytesIO(b""))
        h.token = "abc"
        h.path = "/api/status?token=abc"
        h.headers = {}
        self.assertTrue(h._authorized())

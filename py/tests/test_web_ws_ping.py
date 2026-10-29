"""`web_ws` sunucusu istemci frame'lerini ÇÖZÜYOR mu (stdlib unittest; yalnız 127.0.0.1, gerçek panele DOKUNMAZ).

Regresyon (2026-10-12): `_ws_accept` HTTP isteğini `ServerProtocol`'ün parser'ına hiç göstermiyordu; parser
sonsuza dek "istek satırı" bekliyor, istemciden gelen HİÇBİR frame'i çözmüyordu. Sonuç: Ping'e Pong yok, Close'a
close-ack yok. `websockets` Python istemcisi (varsayılan `ping_interval=20`) 40. sn'de "keepalive ping timeout"
ile bağlantıyı kesiyordu: `cops watch` pencerelerinde traceback + "yeniden bağlanıyor" tekrarının kök nedeni.

Çalıştırma:  python3 py/tests/test_web_ws_ping.py -v
"""
import base64
import http.client
import os
import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from websockets.sync.client import connect
    from claudeops.commands import web_ws
except ImportError as e:  # pragma: no cover
    raise unittest.SkipTest(f"websockets kurulu değil: {e}")


def fetch_fn():
    return {"ok": True, "text": "hello", "cols": 80, "rows": 24, "lite": True}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # web.py'nin _Handler'ıyla aynı

    def do_GET(self):
        if self.path.startswith("/ws/term"):
            web_ws.handle_ws_term(self, fetch_fn)
        elif self.path.startswith("/ws"):
            web_ws.handle_ws(self, lambda: {"sessions": []})
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


def reader_threads():
    return [t for t in threading.enumerate() if t.name.startswith(("ws-reader-", "ws-term-reader-"))]


def wait_until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class ServerFrameHandlingTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def open(self, path="/ws/term?name=x", **kwargs):
        kwargs.setdefault("ping_interval", None)    # kütüphanenin kendi keepalive'ı ölçümü karıştırmasın
        kwargs.setdefault("close_timeout", 3.0)
        conn = connect(f"ws://127.0.0.1:{self.port}{path}", **kwargs)
        self.addCleanup(conn.close)
        return conn

    def test_term_endpoint_answers_a_client_ping_with_a_pong(self):
        conn = self.open()
        self.assertTrue(conn.ping().wait(5), "sunucu Ping'e Pong yollamadı")

    def test_status_endpoint_answers_a_client_ping_with_a_pong(self):
        conn = self.open("/ws")
        self.assertTrue(conn.ping().wait(5), "sunucu Ping'e Pong yollamadı")

    def test_a_keepalive_client_stays_connected_across_several_ping_cycles(self):
        # `cops watch`in kullandığı varsayılan istemci davranışının hızlandırılmış hâli: ping 0.3 sn'de bir,
        # Pong 0.6 sn içinde gelmezse kütüphane bağlantıyı 1011 ile keser. Düzeltmeden önce ~0.9 sn'de kopuyordu.
        conn = self.open(ping_interval=0.3, ping_timeout=0.6)
        time.sleep(1.8)
        self.assertTrue(conn.ping().wait(5))
        self.assertEqual(conn.protocol.state.name, "OPEN")

    def test_server_acknowledges_a_client_close_and_releases_the_connection(self):
        before = set(reader_threads())
        conn = self.open()
        self.assertTrue(wait_until(lambda: set(reader_threads()) - before))
        mine = set(reader_threads()) - before   # bu bağlantının sunucu tarafı reader thread'i
        started = time.monotonic()
        conn.close()
        self.assertLess(time.monotonic() - started, 2.0, "close el sıkışması takıldı (close-ack yok)")
        self.assertTrue(wait_until(lambda: not any(t.is_alive() for t in mine), 5.0),
                        "sunucu tarafı reader thread'i kapanmadı")

    def test_frames_after_the_handshake_are_parsed_even_when_the_request_had_a_huge_header(self):
        # websockets'in Request.parse'ı satır başına 8 KiB sınırı koyar; stdlib http.server 64 KiB'a izin verir.
        from websockets.datastructures import Headers
        from websockets.http11 import Request
        huge = Request(path="/ws", headers=Headers([("Host", "x"), ("Cookie", "a=" + "x" * 9000)]))
        self.assertFalse(web_ws._protocol_fed_with(huge)[1], "ön koşul: parser bu isteği çözemiyor olmalı")
        conn = self.open(additional_headers={"Cookie": "a=" + "x" * 9000})
        self.assertTrue(conn.ping().wait(5))

    def test_first_frame_is_still_delivered(self):
        conn = self.open()
        self.assertIn("hello", conn.recv(timeout=5))

    def raw_handshake(self, target="/ws/term?name=x"):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.addCleanup(sock.close)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode("latin-1"))
        buf = b""
        sock.settimeout(5)      # sunucu thread'i el sıkışmada ölürse (websockets 17.3 ASCII dışı satır) paket asılı kalmasın
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        return sock, buf

    def read_until(self, sock, wanted, timeout=5.0):
        end = time.monotonic() + timeout
        buf = b""
        sock.settimeout(0.2)
        while wanted not in buf and time.monotonic() < end:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
        return buf

    def test_non_ascii_bytes_in_the_request_line_do_not_break_the_handshake_or_frame_parsing(self):
        sock, head = self.raw_handshake("/ws/term?name=\u00fcr\u00fcn")
        self.assertTrue(head.startswith(b"HTTP/1.1 101"), head[:40])
        sock.sendall(b"\x89\x80\x00\x00\x00\x00")      # maskeli boş Ping
        self.assertIn(b"\x8a\x00", self.read_until(sock, b"\x8a\x00"), "Pong gelmedi")

    def test_a_peer_that_starts_the_close_handshake_but_never_closes_tcp_is_dropped_quietly(self):
        # Close frame artık çözülüyor (state CLOSING). Karşı taraf TCP'yi kapatmazsa reader idle-timeout'ta
        # CLOSING durumundayken Ping atmaya çalışıp InvalidState ile ölmemeli; sessizce bırakıp bağlantıyı kapatmalı.
        errors = []
        before = set(reader_threads())
        with mock.patch.object(web_ws, "_READER_IDLE_TIMEOUT_SECONDS", 0.3), \
                mock.patch.object(threading, "excepthook", lambda args: errors.append(args.exc_value)):
            sock, _ = self.raw_handshake()
            self.assertTrue(wait_until(lambda: set(reader_threads()) - before))
            mine = set(reader_threads()) - before
            sock.sendall(b"\x88\x82\x00\x00\x00\x00\x03\xe8")   # maskeli Close 1000
            self.assertIn(b"\x88\x02\x03\xe8", self.read_until(sock, b"\x88\x02\x03\xe8"), "close-ack gelmedi")
            self.assertTrue(wait_until(lambda: not any(t.is_alive() for t in mine), 5.0),
                            "reader thread'i CLOSING'de takılı kaldı")
        self.assertEqual(errors, [])

    def test_plain_http_get_on_a_ws_path_is_rejected_cleanly(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(c.close)
        c.request("GET", "/ws/term?name=x")
        resp = c.getresponse()
        resp.read()
        self.assertNotEqual(resp.status, 101)
        self.assertGreaterEqual(resp.status, 400)


if __name__ == "__main__":
    unittest.main()

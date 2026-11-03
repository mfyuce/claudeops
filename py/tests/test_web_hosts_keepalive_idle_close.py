"""TBD#54 izleme: sunucu (web.py HEADER_READ_TIMEOUT=15 sn) bosta keep-alive baglantiyi kapatirsa web_hosts havuzu
bunu SESSIZCE taze baglantiyla karsilar (hata yok). Gercek yerel soket sunucusu; sabit sleep yok, olay/poll bekler.
Calistirma:  python3 py/tests/test_web_hosts_keepalive_idle_close.py -v
"""
import os
import socket
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.commands import web_hosts  # noqa: E402

BODY = b'{"ok": true}'
RESP = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n"
        b"Connection: keep-alive\r\n\r\n" % len(BODY)) + BODY


class IdleClosingServer:
    """Her baglantida TEK istege yanit verir, sonra (bosta kalma zaman asimi gibi) baglantiyi kapatir."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        self.stop = False
        self.t = threading.Thread(target=self._loop, daemon=True)
        self.t.start()

    def _loop(self):
        self.sock.settimeout(0.1)
        while not self.stop:
            try:
                c, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.accepted += 1
            try:
                c.settimeout(5)
                buf = b""
                while b"\r\n\r\n" not in buf:
                    d = c.recv(4096)
                    if not d:
                        break
                    buf += d
                c.sendall(RESP)
            except OSError:
                pass
            finally:
                c.close()

    def close(self):
        self.stop = True
        self.sock.close()


class KeepAliveIdleCloseTests(unittest.TestCase):
    def setUp(self):
        web_hosts._conn_pool.clear()
        self.srv = IdleClosingServer()
        self.url = f"http://127.0.0.1:{self.srv.port}/x"
        self.addCleanup(self.srv.close)
        self.addCleanup(web_hosts._conn_pool.clear)

    def _wait_pooled_conn_dead(self):
        key = f"http://127.0.0.1:{self.srv.port}"
        end = time.time() + 10
        while time.time() < end:
            bucket = web_hosts._conn_pool.get(key) or []
            if bucket and not web_hosts._conn_is_alive(bucket[-1]):
                return
            time.sleep(0.02)
        self.fail("havuzdaki baglanti kapanmadi")

    def test_peer_closed_idle_connection_is_replaced_silently(self):
        s1, d1, e1 = web_hosts._http_json("GET", self.url, None, 5.0)
        self.assertEqual((s1, d1, e1), (200, {"ok": True}, None))
        self._wait_pooled_conn_dead()
        s2, d2, e2 = web_hosts._http_json("GET", self.url, None, 5.0)
        self.assertEqual((s2, d2, e2), (200, {"ok": True}, None))
        self.assertEqual(self.srv.accepted, 2, "ikinci istek taze baglanti acmali")

    def test_race_dead_conn_judged_alive_is_retried_once_without_error(self):
        # select() kapanisi henuz gormedi (yaris): havuzdan canli sanilan baglanti patlar -> TEK sefer taze retry.
        web_hosts._http_json("GET", self.url, None, 5.0)
        self._wait_pooled_conn_dead()
        with mock.patch.object(web_hosts, "_conn_is_alive", return_value=True):
            s, d, e = web_hosts._http_json("GET", self.url, None, 5.0)
        self.assertEqual((s, d, e), (200, {"ok": True}, None))
        self.assertEqual(self.srv.accepted, 2)


if __name__ == "__main__":
    unittest.main()

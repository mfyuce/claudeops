"""rs/prov G8 ikinci parça: `searxng` spawn yolu. Docker'a dokunulmaz; yalnız loopback test sunucuları ve geçici dizin."""
import os
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import searxng  # noqa: E402


def _serve(replies):
    """Loopback: sırayla verilen ham yanıtları yazar. (port, alınan istek satırları)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(5)
    seen = []

    def run():
        try:
            for reply in replies:
                conn, _ = srv.accept()
                with conn:
                    conn.settimeout(5)
                    seen.append(conn.recv(4096).split(b"\r\n")[0])
                    conn.sendall(reply)
        except OSError:
            pass
        finally:
            srv.close()
    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1], seen


OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"


class Probes(unittest.TestCase):
    def test_health_check_does_not_follow_redirects(self):
        other, seen = _serve([OK])
        port, _ = _serve([b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:%d/x\r\nContent-Length: 0\r\nConnection: close\r\n\r\n" % other])
        self.assertFalse(searxng.healthy(port))
        self.assertEqual(seen, [])

    def test_a_non_http_listener_is_just_unhealthy(self):
        for reply in (b"SSH-2.0-OpenSSH\r\n", b"\x00\x00\r\n"):
            port, _ = _serve([reply])
            self.assertFalse(searxng.healthy(port), reply)

    def test_a_non_http_listener_does_not_stop_recovery(self):
        port, _ = _serve([b"SSH-2.0-OpenSSH\r\n"])
        asked = []

        def inspect():
            asked.append(1)
            return searxng.Box()
        with mock.patch.object(searxng, "_read_state", lambda: {"port": port}), mock.patch.object(searxng, "inspect_box", inspect), \
                mock.patch.object(searxng, "_kick_provision", lambda name: True), mock.patch.object(searxng, "_down_until", 0.0):
            self.assertIsNone(searxng.ensure_search_url("s"))
        self.assertEqual(asked, [1])

    def test_an_infinite_port_is_no_port(self):
        self.assertIsNone(searxng._int(float("inf")))


class Inspect(unittest.TestCase):
    def test_unexpected_shapes_are_docker_unavailable_not_an_exception(self):
        for body in ("{}", '[{"State": "x"}]', '[{"HostConfig": {"PortBindings": {"8080/tcp": 5}}}]'):
            done = mock.Mock(returncode=0, stdout=body, stderr="")
            with mock.patch.object(searxng, "_docker", lambda *a, **k: done):
                with self.assertRaises(searxng.DockerUnavailable, msg=body):
                    searxng.inspect_box()


class State(unittest.TestCase):
    def test_concurrent_updates_keep_both_keys(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(searxng, "STATE_DIR", d):
            real = searxng.atomic_write_json
            first_writing, go = threading.Event(), threading.Event()

            def slow(path, obj, **kw):
                if "a" in obj and "b" not in obj:
                    first_writing.set()
                    go.wait(5)
                real(path, obj, **kw)
            with mock.patch.object(searxng, "atomic_write_json", slow):
                one = threading.Thread(target=lambda: searxng._update_state(a=1))
                two = threading.Thread(target=lambda: searxng._update_state(b=2))
                one.start()
                self.assertTrue(first_writing.wait(5))
                two.start()
                two.join(0.3)
                go.set()
                one.join(5)
                two.join(5)
            self.assertEqual(searxng._read_state(), {"a": 1, "b": 2})


if __name__ == "__main__":
    unittest.main()

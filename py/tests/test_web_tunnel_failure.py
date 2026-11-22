"""TBD#62: tünel URL'i alınamazsa / cloudflared ölürse `_tunnel_failure` hata döner (run() çıkış kodu 1 verir).

Çalıştırma:  python3 py/tests/test_web_tunnel_failure.py -v
"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402


class TunnelFailure(unittest.TestCase):
    def test_ok(self):
        p = SimpleNamespace(poll=lambda: None, returncode=None)
        self.assertEqual(web._tunnel_failure(p, "https://x.trycloudflare.com"), "")

    def test_no_url(self):
        p = SimpleNamespace(poll=lambda: None, returncode=None)
        self.assertIn("URL", web._tunnel_failure(p, None))

    def test_process_died_even_with_url(self):
        p = SimpleNamespace(poll=lambda: 1, returncode=1)
        self.assertIn("kod 1", web._tunnel_failure(p, "https://x"))

    def test_no_proc_no_url(self):
        self.assertTrue(web._tunnel_failure(None, ""))

class TunnelRegistered(unittest.TestCase):
    """Ölü URL: cloudflared URL'i basar ama edge'e bağlanamazsa (7844 kapalı) URL verilmemeli (TODO 1137)."""

    def _fake(self, tmp, body):
        import stat
        path = os.path.join(tmp, "fake-cloudflared")
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\nsleep 30\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def _run(self, body, timeout):
        import tempfile, shutil
        tmp = tempfile.mkdtemp()
        old = web.TUNNEL_LOG
        web.TUNNEL_LOG = os.path.join(tmp, "t.log")
        proc = None
        try:
            proc, url = web._start_tunnel(1, self._fake(tmp, body), timeout=timeout)
            return url
        finally:
            web.TUNNEL_LOG = old
            if proc is not None:
                proc.kill(); proc.wait()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_url_without_registration_is_not_returned(self):
        self.assertIsNone(self._run('echo "https://abc-def.trycloudflare.com"', 2.0))

    def test_url_with_registration_is_returned(self):
        url = self._run('echo "https://abc-def.trycloudflare.com"; echo "INF Registered tunnel connection connIndex=0"', 5.0)
        self.assertEqual(url, "https://abc-def.trycloudflare.com")

    def test_registration_marker_logged_before_url_still_ok(self):
        url = self._run('echo "Registered tunnel connection"; echo "https://abc.trycloudflare.com"', 5.0)
        self.assertEqual(url, "https://abc.trycloudflare.com")


class PortBusyGuard(unittest.TestCase):
    """Port doluyken tünel hiç başlamaz (cloudflared çalışan paneli internete açmasın; review R-2/R-4)."""

    def test_port_in_use_detects_listener(self):
        import socket
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        try:
            self.assertTrue(web._port_in_use("127.0.0.1", srv.getsockname()[1]))
        finally:
            srv.close()

    def test_free_port_not_busy(self):
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        self.assertEqual(web._port_in_use("127.0.0.1", port), "")


if __name__ == "__main__":
    unittest.main()

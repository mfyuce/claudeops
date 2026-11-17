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

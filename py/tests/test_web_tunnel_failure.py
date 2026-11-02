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


if __name__ == "__main__":
    unittest.main()

"""GATE-TODO 22/23: WS proxy backend soketi bağlandıktan sonra timeout'suz; indirme ASCII yedek adı gerçekten ASCII.

Çalıştırma:  python3 py/tests/test_web_download_name.py -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "claudeops", "commands", "web.py"), encoding="utf-8").read()


class DownloadNameTests(unittest.TestCase):
    def test_ascii_fallback_is_ascii_and_safe(self):
        m = re.search(r'ascii_name = (.+)', SRC)
        self.assertIsNotNone(m)
        for fn in ("rapor çalışması.txt", 'a"b\r\n.txt', "日本語.md", "düz.txt", ""):
            filename = fn
            ascii_name = eval(m.group(1))
            ascii_name.encode("ascii")
            self.assertNotIn('"', ascii_name)
            self.assertNotIn("\n", ascii_name)
            self.assertTrue(ascii_name)
        self.assertEqual(eval(m.group(1).replace("filename", "'düz.txt'")), "d_z.txt")

    def test_ws_proxy_clears_connect_timeout(self):
        i = SRC.index('socket.create_connection(("127.0.0.1", port), timeout=5.0)')
        self.assertIn("backend.settimeout(None)", SRC[i:i + 200])


if __name__ == "__main__":
    unittest.main()

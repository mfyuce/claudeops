import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import chat_remote as cr  # noqa: E402
from claudeops.commands import web_hosts as H  # noqa: E402


class PanelTransportTest(unittest.TestCase):
    def test_idle_strips_ansi_prompt(self):
        tr = cr.PanelTransport("h", "s")
        out = {"ok": True, "text": "x\n\x1b[01;32muser@h\x1b[00m:\x1b[01;34m~\x1b[00m$ "}
        with mock.patch.object(H, "proxy_get", return_value=(out, 200)):
            self.assertTrue(tr.idle())

    def test_download_rejects_non_200(self):
        tr = cr.PanelTransport("h", "s")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(H, "proxy_get_raw", return_value=(b'{"ok":false}', 404, {}, None)):
            dest = os.path.join(d, "a.tgz")
            with self.assertRaises(RuntimeError):
                tr.download("/r", "a.tgz", dest)
            self.assertFalse(os.path.exists(dest))

    def test_download_ok(self):
        tr = cr.PanelTransport("h", "s")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(H, "proxy_get_raw", return_value=(b"DATA", 200, {}, None)):
            dest = os.path.join(d, "a.tgz")
            self.assertEqual(tr.download("/r", "a.tgz", dest), 4)
            self.assertEqual(open(dest, "rb").read(), b"DATA")


if __name__ == "__main__":
    unittest.main()

"""ok:false yanıtlarında makine-okur `code` (TODO 1177); watch.classify_frame önce koda bakar. Ağ yok."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web, watch  # noqa: E402


class ErrorCodeTest(unittest.TestCase):
    def test_err_carries_catalog_key_as_code(self):
        r = web._err("en", "not_running", name="x")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "not_running")
        self.assertIn("not running", r["error"])

    def test_classify_prefers_code_over_text(self):
        self.assertEqual(watch.classify_frame({"ok": False, "error": "metin degisti", "code": "host_unreachable"})[0], "reconnecting")
        self.assertEqual(watch.classify_frame({"ok": False, "error": "metin degisti", "code": "relay_connecting"})[0], "reconnecting")
        self.assertEqual(watch.classify_frame({"ok": False, "error": "unreachable gibi", "code": "not_running"})[0], "waiting")

    def test_classify_falls_back_to_text_without_code(self):
        self.assertEqual(watch.classify_frame({"ok": False, "error": "yuhem unreachable: x"})[0], "reconnecting")
        self.assertEqual(watch.classify_frame({"ok": False, "error": "x: not running"})[0], "waiting")


if __name__ == "__main__":
    unittest.main()

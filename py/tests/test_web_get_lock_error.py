"""Kapı 1. tur madde 3: GET yolunda alınamayan durum dosyası kilidi bağlantıyı düşürmesin, POST gibi 503 dönsün."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.atomic_json import LockError  # noqa: E402
from claudeops.commands import web  # noqa: E402


class GetLockError(unittest.TestCase):
    def test_get_returns_503_and_closes(self):
        h = web._Handler.__new__(web._Handler)
        h.path = "/api/status?token=gizli"
        h.close_connection = False
        sent = []
        h._json = lambda obj, status=200: sent.append((status, obj))
        with mock.patch.object(h, "_do_get_inner", side_effect=LockError("kilit")), \
                mock.patch.object(web, "diag_log") as log:
            h.do_GET()
        self.assertEqual(sent, [(503, {"ok": False, "error": "state file is locked, retry"})])
        self.assertTrue(h.close_connection)
        log.assert_called_once_with("get_lock_busy", path="/api/status", error="kilit")


if __name__ == "__main__":
    unittest.main()

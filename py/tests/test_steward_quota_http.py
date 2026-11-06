"""Panel kota ayarı uçları: GET /api/steward/quota (ayar + durum), POST (yalnız insan, doğrulamalı). Ayar dosyası GEÇİCİ."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import settings  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class QuotaHttp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(settings, "SETTINGS_JSON", os.path.join(self.tmp.name, "settings.json"))
        self.p.start()
        self.log = mock.patch.object(ws.sw, "log_event", lambda *a, **k: None)
        self.log.start()

    def tearDown(self):
        self.log.stop()
        self.p.stop()
        self.tmp.cleanup()

    def test_brain_denied(self):
        r = ws.http_quota_set({"actor": "brain", "key": "mode", "value": "auto"})
        self.assertFalse(r["ok"])
        self.assertEqual(ws.quota_config(), {})

    def test_set_and_get(self):
        self.assertTrue(ws.http_quota_set({"key": "mode", "value": "manual"})["ok"])
        self.assertTrue(ws.http_quota_set({"key": "manual_limit", "value": 93})["ok"])
        self.assertTrue(ws.http_quota_set({"key": "day_tue", "value": "80"})["ok"])
        g = ws.http_quota()
        self.assertEqual(g["config"]["mode"], "manual")
        self.assertEqual(g["config"]["manual_limit"], "93")
        self.assertEqual(g["config"]["day_tue"], "80")
        self.assertIn("auto", g["modes"])

    def test_day_empty_deletes(self):
        ws.http_quota_set({"key": "day_tue", "value": "80"})
        ws.http_quota_set({"key": "day_tue", "value": ""})
        self.assertNotIn("day_tue", ws.quota_config())

    def test_validation(self):
        for k, v in (("mode", "x"), ("manual_limit", 101), ("manual_limit", "abc"), ("poll_minutes", 0),
                     ("day_xyz", 5), ("evil", 1), ("final_limit", True)):
            self.assertFalse(ws.http_quota_set({"key": k, "value": v})["ok"], (k, v))
        self.assertEqual(ws.quota_config(), {})

    def test_routes_registered(self):
        self.assertIn("quota", ws._GET_PATHS)
        self.assertIs(ws.http_get("/api/steward/quota", {})["ok"], True)


if __name__ == "__main__":
    unittest.main()

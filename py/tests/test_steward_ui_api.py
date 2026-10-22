"""Panel uçları: ayar yazma, aç/kapat, bekleyen madde listesi. Gerçek settings.json'a DOKUNMAZ (`_Tmp` geçici dizin);
başında/sonunda gerçek dosyanın sha256'sı karşılaştırılır.

Çalıştırma: python3 -m unittest discover -s py/tests"""
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

_REAL = os.path.expanduser("~/.claude/claudeops/settings.json")


def _sha():
    try:
        with open(_REAL, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


_BEFORE = _sha()


def tearDownModule():
    if _sha() != _BEFORE:
        raise AssertionError("gerçek settings.json test sırasında değişti")


class UiConfigTest(_Tmp):
    def test_config_writes_valid_int_and_mode(self):
        self.assertTrue(ws.http_config({"key": "tour_minutes", "value": "20"}, "default")["ok"])
        self.assertEqual(ws.steward_config("default").tour_minutes, 20)
        self.assertTrue(ws.http_config({"key": "mode", "value": "act"}, "default")["ok"])
        self.assertEqual(ws.steward_config("default").mode, "act")

    def test_config_rejects_bad_values_and_unknown_fields(self):
        for body in ({"key": "tour_minutes", "value": "0"}, {"key": "tour_minutes", "value": "abc"},
                     {"key": "mode", "value": "yolo"}, {"key": "brain_model", "value": "x"}, {"key": "enabled", "value": "on"}):
            r = ws.http_config(body, "default")
            self.assertFalse(r["ok"], body)

    def test_brain_cannot_change_config_or_enable(self):
        self.assertFalse(ws.http_config({"key": "tour_minutes", "value": 5, "actor": "brain"}, "default")["ok"])
        self.assertFalse(ws.http_enable({"enabled": True, "actor": "brain"}, "default")["ok"])

    def test_enable_toggles(self):
        self.assertTrue(ws.http_enable({"enabled": True}, "default")["ok"])
        self.assertTrue(ws.steward_config("default").enabled)
        self.assertTrue(ws.http_enable({"enabled": False}, "default")["ok"])
        self.assertFalse(ws.steward_config("default").enabled)


if __name__ == "__main__":
    unittest.main()

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


class UiIdentityTest(_Tmp):
    """Kimlik create/remove/transfer uçları (CLI mantığının HTTP karşılığı)."""

    def setUp(self):
        super().setUp()
        from unittest import mock
        self._p = mock.patch.object(ws, "find_sessions", lambda **kw: [])
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_create_validates_and_opens_off_observe(self):
        for bad in ("", "default", "A1", "degnekciz", "x"):
            self.assertFalse(ws.http_identity_create({"target": bad})["ok"], bad)
        self.assertTrue(ws.http_identity_create({"target": "kitap", "label": "Kitaplar"})["ok"])
        cfg = ws.steward_config("kitap")
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.mode, "observe")
        self.assertFalse(ws.http_identity_create({"target": "kitap"})["ok"])      # zaten var

    def test_brain_cannot_manage_identities(self):
        for fn, body in ((ws.http_identity_create, {"target": "kitap"}), (ws.http_identity_remove, {"target": "kitap"}),
                         (ws.http_identity_transfer, {"project": "a", "to": "kitap"})):
            self.assertFalse(fn(dict(body, actor="brain"))["ok"])

    def test_remove_refuses_default_unknown_and_nonempty(self):
        self.assertFalse(ws.http_identity_remove({"target": "default"})["ok"])
        self.assertFalse(ws.http_identity_remove({"target": "nope"})["ok"])
        ws.http_identity_create({"target": "kitap"})
        sw.save_projects({"ncs": sw.Project(name="ncs")}, "kitap")
        r = ws.http_identity_remove({"target": "kitap"})
        self.assertFalse(r["ok"])
        self.assertIn("ncs", r["error"])

    def test_remove_empty_identity(self):
        ws.http_identity_create({"target": "kitap"})
        self.assertTrue(ws.http_identity_remove({"target": "kitap"})["ok"])
        self.assertNotIn("kitap", ws.steward_ids())

    def test_transfer_moves_project_and_refuses_running(self):
        from unittest import mock
        ws.http_identity_create({"target": "kitap"})
        sw.save_projects({"ncs": sw.Project(name="ncs")}, "default")
        self.assertFalse(ws.http_identity_transfer({"project": "ncs", "to": "nope"})["ok"])
        fake = mock.Mock()
        fake.name = "ncs"
        with mock.patch.object(ws, "find_sessions", lambda **kw: [fake]):
            r = ws.http_identity_transfer({"project": "ncs", "to": "kitap"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["running"], "ncs")
        r = ws.http_identity_transfer({"project": "ncs", "to": "kitap"})
        self.assertTrue(r["ok"], r)
        self.assertIn("ncs", sw.load_projects("kitap"))
        self.assertNotIn("ncs", sw.load_projects("default"))


if __name__ == "__main__":
    unittest.main()

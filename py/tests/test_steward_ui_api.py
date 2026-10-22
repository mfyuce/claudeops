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

    def test_drain_toggle_and_brain_directive_gate(self):
        self.assertTrue(ws.http_config({"key": "drain", "value": True}, "default")["ok"])
        self.assertTrue(ws.steward_config("default").drain)
        sw.save_projects({"ncs": sw.Project(name="ncs")}, "default")
        r = ws.http_directive({"name": "ncs", "text": "x", "actor": "brain"}, "default")
        self.assertEqual(r.get("code"), "draining")
        self.assertTrue(ws.http_config({"key": "drain", "value": False}, "default")["ok"])
        self.assertFalse(ws.steward_config("default").drain)

    def test_enable_toggles(self):
        self.assertTrue(ws.http_enable({"enabled": True}, "default")["ok"])
        self.assertTrue(ws.steward_config("default").enabled)
        self.assertTrue(ws.http_enable({"enabled": False}, "default")["ok"])
        self.assertFalse(ws.steward_config("default").enabled)


class UiShutdownStateTest(_Tmp):
    def test_state_exposes_shutdown_only_when_started(self):
        self.assertNotIn("shutdown", ws.http_state())
        sw.save_state({"shutdown": {"started": 1.0, "items": {"ncs": {"stage": "ho", "at": 2.0, "blocked": "x"}}}}, "default")
        got = ws.http_state()["shutdown"]
        self.assertEqual(got["items"]["ncs"], {"stage": "ho", "blocked": "x"})
        self.assertFalse(got["cancelled"])


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


class UiServiceJobTest(_Tmp):
    """Servis ekle/sil/liste ve iş ack uçları; token değeri ASLA dönmez."""

    def setUp(self):
        super().setUp()
        self.tok = os.path.join(self.dir.name, "t.token")
        with open(self.tok, "w") as f:
            f.write("SECRET-TOKEN-VALUE\n")
        os.chmod(self.tok, 0o600)

    def test_add_list_hides_token_and_rm(self):
        r = ws.http_service_add({"name": "varaka", "url": "http://127.0.0.1:9", "token_file": self.tok})
        self.assertTrue(r["ok"], r)
        lst = ws.http_services()
        self.assertEqual([x["name"] for x in lst["services"]], ["varaka"])
        self.assertTrue(lst["services"][0]["token_present"])
        self.assertNotIn("SECRET-TOKEN-VALUE", repr(lst))
        self.assertFalse(ws.http_service_add({"name": "varaka", "url": "http://127.0.0.1:9", "token_file": self.tok})["ok"])
        self.assertTrue(ws.http_service_rm({"name": "varaka"})["ok"])
        self.assertFalse(ws.http_service_rm({"name": "varaka"})["ok"])

    def test_add_validates_and_brain_refused(self):
        for body in ({"name": "x1", "url": "ftp://h", "token_file": self.tok},
                     {"name": "x2", "url": "http://h", "token_file": "/nope/token"}):
            self.assertFalse(ws.http_service_add(body)["ok"], body)
        self.assertFalse(ws.http_service_add({"name": "okay", "url": "http://h", "token_file": self.tok, "actor": "brain"})["ok"])
        self.assertFalse(ws.http_service_rm({"name": "okay", "actor": "brain"})["ok"])
        self.assertFalse(ws.http_job_ack({"id": "1", "actor": "brain"})["ok"])

    def test_rm_refused_with_open_job_and_ack_only_terminal(self):
        from claudeops import steward_jobs as sj
        ws.http_service_add({"name": "varaka", "url": "http://127.0.0.1:9", "token_file": self.tok})
        sj.save_record(sj.new_record("varaka", 7, "ncs", "embed", "running", "k1"), "default")
        r = ws.http_service_rm({"name": "varaka"})
        self.assertFalse(r["ok"])
        self.assertIn("open job", r["error"])
        self.assertFalse(ws.http_job_ack({"id": "7", "service": "varaka"})["ok"])          # açık iş: ack reddedilir
        sj.save_record(sj.new_record("varaka", 8, "ncs", "embed", "done", "k2"), "default")
        self.assertTrue(ws.http_job_ack({"id": "8", "service": "varaka"})["ok"])
        self.assertFalse(ws.http_job_ack({"id": "99"})["ok"])


if __name__ == "__main__":
    unittest.main()

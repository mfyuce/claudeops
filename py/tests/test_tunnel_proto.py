"""`tunnel_protocol` ayarı: drop-in yazımı, yalnız değişince tünel restart'ı, doğrulama (systemctl'e dokunmadan)."""
import os
import tempfile
import unittest
from unittest import mock

from claudeops import settings, tunnel_proto
from claudeops.commands import web


class Dropin(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.restarts = []

    def apply(self, v):
        with mock.patch("threading.Timer") as T:
            res = tunnel_proto.apply(v, home=self.home, restart=lambda: self.restarts.append(1))
            self.timer = T
        return res

    def read(self):
        return open(tunnel_proto.dropin_path(self.home)).read()

    def test_http2_written_and_restart_scheduled(self):
        r = self.apply("http2")
        self.assertEqual(r, {"changed": True, "restart": True})
        self.assertEqual(self.read(), "[Service]\nEnvironment=CLAUDEOPS_TUNNEL_PROTOCOL=http2\n")
        self.timer.assert_called_once()

    def test_same_value_no_restart(self):
        self.apply("quic")
        r = self.apply("QUIC ")
        self.assertEqual(r, {"changed": False, "restart": False})
        self.timer.assert_not_called()

    def test_auto_writes_empty_env_overriding_manual_dropin(self):
        self.apply("http2")
        r = self.apply("auto")
        self.assertTrue(r["changed"])
        self.assertEqual(self.read(), "[Service]\nEnvironment=CLAUDEOPS_TUNNEL_PROTOCOL=\n")

    def test_empty_means_unmanaged_file_untouched(self):
        self.apply("http2")
        before = self.read()
        r = self.apply("")
        self.assertEqual(r, {"changed": False, "restart": False})
        self.assertEqual(self.read(), before)

    def test_unknown_value_is_unmanaged(self):
        self.assertEqual(self.apply("tcp"), {"changed": False, "restart": False})
        self.assertFalse(os.path.exists(tunnel_proto.dropin_path(self.home)))


class SavePath(unittest.TestCase):
    def test_default_unmanaged(self):
        self.assertEqual(settings.DEFAULT_SETTINGS["tunnel_protocol"], "")

    def test_invalid_rejected_before_save(self):
        with mock.patch.object(web, "save_settings") as sv, mock.patch.object(tunnel_proto, "apply") as ap:
            res = web._save_settings({"tunnel_protocol": "tcp"})
        self.assertFalse(res["ok"])
        sv.assert_not_called()
        ap.assert_not_called()

    def test_valid_saves_then_applies_and_reports(self):
        with mock.patch.object(web, "save_settings", return_value={**settings.DEFAULT_SETTINGS, "tunnel_protocol": "http2"}), \
             mock.patch.object(tunnel_proto, "apply", return_value={"changed": True, "restart": True}) as ap:
            res = web._save_settings({"tunnel_protocol": "http2"})
        ap.assert_called_once_with("http2")
        self.assertTrue(res["ok"])
        self.assertEqual(res["tunnel"], {"changed": True, "restart": True})

    def test_other_settings_do_not_touch_tunnel(self):
        with mock.patch.object(web, "save_settings", return_value=dict(settings.DEFAULT_SETTINGS)), \
             mock.patch.object(tunnel_proto, "apply") as ap:
            res = web._save_settings({"layout_grid": "4"})
        ap.assert_not_called()
        self.assertNotIn("tunnel", res)


if __name__ == "__main__":
    unittest.main()

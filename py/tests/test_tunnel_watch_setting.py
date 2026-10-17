"""`tunnel_watch` ayarı: tünel sağlık bekçisinin Ayarlar'dan açılıp kapanması (stdlib unittest).

Çalıştırma:  python3 py/tests/test_tunnel_watch_setting.py -v

Kapsadığı iş (kullanıcı, 2026-10-17: "settingslerde seçimlik olsun"): `data/run-tunnel.sh`'ın sağlık bekçisi
(art arda HTTP 530'da cloudflared'ı sonlandırır, systemd yeni tüneli açar, URL değişir) Ayarlar > Genel'den
açılıp kapanabilmeli. Anahtar `settings.json`'daki `tunnel_watch` ("on" varsayılan); betik her yoklamada okur
(`test_run_tunnel_script.py` bunu bash tarafında sınar), burası Python tarafı: şema, okuyucu, kaydetme ve
panelin tarayıcıya yolladığı ayarlar. Gerçek settings.json'a, tünele ya da ağa DOKUNMAZ.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import settings  # noqa: E402
from claudeops.commands import web  # noqa: E402


class TunnelWatchSettingTests(unittest.TestCase):
    def enabled(self, value):
        with mock.patch.object(settings, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, "tunnel_watch": value}):
            return settings.tunnel_watch_enabled()

    def test_the_watchdog_is_on_by_default(self):
        self.assertEqual(settings.DEFAULT_SETTINGS["tunnel_watch"], "on")
        with mock.patch.object(settings, "load_settings", lambda: dict(settings.DEFAULT_SETTINGS)):
            self.assertTrue(settings.tunnel_watch_enabled())

    def test_on_in_any_case_and_odd_values_mean_enabled(self):
        for value in ("on", "ON", " on ", "", None, "açık", "yes", "1", "true", 1, True):
            with self.subTest(value=value):
                self.assertTrue(self.enabled(value))

    def test_every_off_spelling_disables_it_including_non_strings(self):
        for value in ("off", "OFF", " 0 ", "false", "no", "n", "hayir", "kapali", "kapalı", "disabled", "none", False, 0):
            with self.subTest(value=value):
                self.assertFalse(self.enabled(value))

    def test_a_missing_key_in_a_stored_file_falls_back_to_the_default(self):
        """settings.json'da anahtar yoksa `load_settings` DEFAULT_SETTINGS'i karıştırır: açık."""
        with mock.patch.object(settings, "SETTINGS_JSON", "/nonexistent/settings.json"):
            self.assertTrue(settings.tunnel_watch_enabled())

    def test_the_value_round_trips_through_save_settings_as_a_plain_scalar(self):
        written = {}
        with mock.patch.object(settings, "load_settings", lambda: dict(settings.DEFAULT_SETTINGS)), \
                mock.patch.object(settings, "atomic_write_json", lambda path, data, **kw: written.update(data)):
            out = settings.save_settings({"tunnel_watch": "off"})
        self.assertEqual(out["tunnel_watch"], "off")
        self.assertEqual(written["tunnel_watch"], "off")

    def test_the_panel_sends_the_value_to_the_browser_unredacted(self):
        """Sır değil: byok gibi maskelenmez, Ayarlar'daki seçici bunu okur."""
        wire = web._redact_settings_for_wire({**settings.DEFAULT_SETTINGS, "tunnel_watch": "off", "byok": {"ucli": {"K": "gizli"}}})
        self.assertEqual(wire["tunnel_watch"], "off")
        self.assertEqual(wire["byok"], {"ucli": {"K": True}})

    def test_saving_it_through_the_web_handler_is_accepted(self):
        with mock.patch.object(web, "save_settings", lambda patch: {**settings.DEFAULT_SETTINGS, **patch}) as saved:
            result = web._save_settings({"tunnel_watch": "off"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["settings"]["tunnel_watch"], "off")
        self.assertIsNotNone(saved)


if __name__ == "__main__":
    unittest.main()

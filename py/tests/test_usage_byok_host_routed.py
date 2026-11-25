"""Sahip kararı 22 Kas (TBD#69): kullanım tek hosttan okunur; uzağa yalnız tek BYOK alanı yazılır, düz http'ye anahtar gitmez."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import authz, settings  # noqa: E402
from claudeops.commands import web, web_hosts  # noqa: E402


class Routing(unittest.TestCase):
    def test_routed_but_whole_settings_stays_local(self):
        self.assertIn("/api/usage", web_hosts.HOST_ROUTED_PATHS)
        self.assertIn("/api/settings/byok", web_hosts.HOST_ROUTED_PATHS)
        self.assertNotIn("/api/settings", web_hosts.HOST_ROUTED_PATHS)

    def test_byok_needs_admin_config(self):
        self.assertEqual(authz.action_for("POST", "/api/settings/byok"), "admin.config")

    def _proxy(self, url, body):
        with mock.patch.object(web_hosts.hosts_mod, "get_host", return_value={"name": "h", "base_url": url, "token": "t"}), \
             mock.patch.object(web_hosts, "_http_json", return_value=(200, {"ok": True}, None)) as send:
            res, _ = web_hosts.proxy_action("/api/settings/byok", "h", body)
        return res, send

    def test_secret_not_sent_over_plain_http(self):
        res, send = self._proxy("http://10.0.0.5:8765", {"cli": "ucli", "env": "K", "value": "s"})
        self.assertEqual(res.get("code"), "insecure_host")
        send.assert_not_called()

    def test_https_loopback_and_status_read_pass(self):
        for url, body in (("https://h.example", {"value": "s"}), ("http://127.0.0.1:9", {"value": "s"}), ("http://10.0.0.5", {})):
            res, send = self._proxy(url, body)
            self.assertTrue(res["ok"], url)
            send.assert_called_once()


class Endpoint(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for p in (mock.patch.object(settings, "SETTINGS_JSON", os.path.join(d.name, "settings.json")),
                  mock.patch("claudeops.statedocs.read_json", lambda name, path, default: _read(path, default)),
                  mock.patch("claudeops.statedocs.write_json", lambda name, path, data, mode=None, writer=None: writer(path, data, mode=mode))):
            p.start()
            self.addCleanup(p.stop)

    def test_set_read_clear_never_echoes_value(self):
        settings.save_settings({"byok": {"copilot": {"OTHER_KEY": "keep"}}, "theme": "dark"})
        res = web._settings_byok({"cli": "ucli", "env": "MY_KEY", "value": "secret-1"})
        self.assertEqual(res, {"ok": True, "byok": {"copilot": {"OTHER_KEY": True}, "ucli": {"MY_KEY": True}}})
        self.assertEqual(web._settings_byok({"host": "local"}), res)
        self.assertEqual(settings.byok_env_for("ucli"), {"MY_KEY": "secret-1"})
        res = web._settings_byok({"cli": "ucli", "env": "MY_KEY", "value": ""})
        self.assertEqual(res["byok"], {"copilot": {"OTHER_KEY": True}})
        self.assertEqual(settings.load_settings()["theme"], "dark")

    def test_rejects_bad_input_without_writing(self):
        for bad in ({"cli": "nope", "env": "K", "value": "v"}, {"cli": "ucli", "env": "k;x", "value": "v"},
                    {"cli": "ucli", "env": "K", "value": 5}, {"cli": "ucli", "env": "K", "value": "a\nb"},
                    {"value": "v"}):
            self.assertFalse(web._settings_byok(bad)["ok"], bad)
        self.assertEqual(settings.load_settings().get("byok"), {})


def _read(path, default):
    import json
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


if __name__ == "__main__":
    unittest.main()

"""TBD#397 soru 1 (a): bozuk `settings.json` ya da geçersiz `ucli_cost.daily_cap_usd` günlük tavanı sessizce KAPATMAZ,
Claude hizmetli yeni oturum reddedilir. Her şey geçici dizinde."""
import json
import os
import shlex
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claudeops import settings, ucli_client, ucli_cost  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from test_ucli_web import HELP_BOTH, fake_ucli  # noqa: E402


class _Settings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.path = os.path.join(self.tmp, "settings.json")
        self.usage = os.path.join(self.tmp, "usage")
        for p in (mock.patch.object(settings, "SETTINGS_JSON", self.path),
                  mock.patch.object(ucli_cost, "USAGE_DIR", self.usage)):
            p.start()
            self.addCleanup(p.stop)
        self.reset()
        self.addCleanup(self.reset)

    def reset(self):
        settings._LOAD_CACHE.update(sig=None, val=None)
        ucli_cost.invalidate()
        ucli_cost._RESERVED.clear()

    def write(self, data):
        with open(self.path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        self.reset()

    def reserve(self):
        ucli_cost.reserve("s", base=self.usage)

    def assert_refused(self, why):
        with self.assertRaises(ValueError) as cm:
            self.reserve()
        self.assertNotIsInstance(cm.exception, ucli_cost.DailyCapExceeded)
        self.assertEqual(str(cm.exception),
                         f"claude: günlük USD tavanı denetlenemiyor ({why}); settings.json'ı düzelt "
                         "(ucli_cost.daily_cap_usd: 0 = tavan yok ya da pozitif sayı)")
        self.assertEqual(ucli_cost._RESERVED, {})
        self.assertNotIn("code", ucli_cost.refusal(cm.exception))


class BrokenDocumentRefuses(_Settings):
    def test_unparsable_or_non_object_documents(self):
        for data in ("{bozuk", "", "[]", "5", "null", b'\xff\xfe{"a": 1}'):
            self.write(data)
            self.assert_refused("settings.json okunamadı ya da bozuk")

    def test_directory_and_fifo(self):
        os.mkdir(self.path)
        self.assert_refused("settings.json okunamadı ya da bozuk")
        os.rmdir(self.path)
        os.mkfifo(self.path)
        with mock.patch.object(ucli_cost, "ucli_cost_config",
                               lambda: {"daily_cap_usd": 0.0, "credit_total_usd": 0.0, "cache_ttl": "5m"}):
            self.assert_refused("settings.json okunamadı ya da bozuk")

    @unittest.skipIf(os.getuid() == 0, "root izinleri aşar")
    def test_unreadable_file(self):
        self.write('{"ucli_cost": {"daily_cap_usd": 5}}')
        os.chmod(self.path, 0)
        self.assert_refused("settings.json okunamadı ya da bozuk")


class InvalidCapRefuses(_Settings):
    def test_invalid_values(self):
        for raw in ('"abc"', '"-5"', "-5", '"inf"', "Infinity", "NaN", "1e400", "true", "false", "[]", "{}", "[20]"):
            self.write('{"ucli_cost": {"daily_cap_usd": %s}}' % raw)
            self.assert_refused("ucli_cost.daily_cap_usd geçersiz")

    def test_invalid_block(self):
        for raw in ('"bozuk"', "5", "[]", "false"):
            self.write('{"ucli_cost": %s}' % raw)
            self.assert_refused("ucli_cost ayarı geçersiz")


class NoCapStaysOpen(_Settings):
    def test_missing_file(self):
        self.reserve()

    def test_dangling_link_is_a_missing_file(self):
        os.symlink(os.path.join(self.tmp, "yok"), self.path)
        self.reserve()

    def test_absent_or_zero_or_empty(self):
        for doc in ({}, {"ucli_cost": {}}, {"ucli_cost": None}, {"ucli_cost": ""}, {"ucli_cost": {"cache_ttl": "5m"}},
                    *({"ucli_cost": {"daily_cap_usd": v}} for v in (0, 0.0, -0.0, "0", "0,0", " 0 ", "", "  ", None))):
            self.write(json.dumps(doc))
            self.reserve()
            self.assertEqual(ucli_cost._RESERVED, {}, doc)

    def test_valid_cap_still_applies(self):
        for v in (5, "5", "1,5", " 20 "):
            self.write(json.dumps({"ucli_cost": {"daily_cap_usd": v}}))
            self.reserve()
            self.assertIn("s", ucli_cost._RESERVED, v)


class OnlyTheClaudeServiceIsAffected(_Settings):
    def build(self, opts):
        help_text = HELP_BOTH + "      --provider <P>\n      --api-key-env <E>\n"
        binary = fake_ucli(self.tmp, help_text)
        ucli_client._HELP_CACHE.clear()
        self.addCleanup(ucli_client._HELP_CACHE.clear)
        keys = {"ANTHROPIC_API_KEY": "sk-x", "XAI_API_KEY": "k"}
        with mock.patch.object(up, "resolve_binary", lambda: binary), \
                mock.patch.object(up, "_sync_api_key_file", lambda: False), \
                mock.patch.object(up, "diag_log", lambda *a, **k: None), \
                mock.patch.object(up, "byok_env_for", lambda cli: dict(keys)), \
                mock.patch.object(up, "_service_key_file", lambda s: os.path.join(self.tmp, f"key_{s}")), \
                mock.patch.object(up, "_web_args", lambda *a, **k: []), \
                mock.patch.object(up, "_script_args", lambda *a, **k: []), \
                mock.patch.object(up, "_stream_args", lambda *a, **k: []), \
                mock.patch.object(up, "_state_dir_args", lambda *a, **k: []), \
                mock.patch.object(up, "_effort_args", lambda *a, **k: []), \
                mock.patch.object(up.ucli_cost, "OTHER_DIR", os.path.join(self.usage, "other")):
            return up.UcliProvider().build_inner_command("/w/proj", "m", "allow-edit", "high", None, "", "vc",
                                                         cli_opts=opts)

    def test_broken_settings_refuse_claude_only(self):
        self.write("{bozuk")
        self.assertTrue(shlex.split(self.build(None)))
        self.assertTrue(shlex.split(self.build({"service": "grok"})))
        with self.assertRaises(ValueError) as cm:
            self.build({"service": "claude"})
        self.assertIn("settings.json", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

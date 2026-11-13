"""byok sağlayıcı bakiye okuması: anahtar yalnız başlıkta, ücretsiz uç yoksa dürüst no_endpoint, hata metnine anahtar girmez."""
import io
import json
import unittest
import urllib.error
from unittest import mock

from claudeops import api_balance

KEY = "sk-or-v1-SECRETSECRET"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Balance(unittest.TestCase):
    def test_openrouter_parses_and_key_only_in_header(self):
        seen = {}

        def opener(req, timeout=None):
            seen["url"], seen["auth"], seen["timeout"] = req.full_url, req.get_header("Authorization"), timeout
            return _Resp(json.dumps({"data": {"usage": 1.5, "limit": 10, "limit_remaining": 8.5}}).encode())

        res = api_balance.openrouter(KEY, opener)
        self.assertTrue(res["available"])
        self.assertNotIn(KEY, seen["url"])
        self.assertEqual(seen["auth"], "Bearer " + KEY)
        self.assertEqual(res["entries"][1]["percent"], "15")
        self.assertNotIn(KEY, json.dumps(res))

    def test_openrouter_no_limit(self):
        opener = lambda req, timeout=None: _Resp(json.dumps({"data": {"usage": 0, "limit": None}}).encode())
        res = api_balance.openrouter(KEY, opener)
        self.assertEqual(res["entries"][1]["detail"], "limit yok")

    def test_openrouter_errors(self):
        def auth(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)

        def net(req, timeout=None):
            raise OSError(f"boom {KEY}")

        self.assertEqual(api_balance.openrouter(KEY, auth)["reason"], "auth_failed")
        r = api_balance.openrouter(KEY, net)
        self.assertEqual(r["reason"], "request_failed")
        self.assertNotIn(KEY, json.dumps(r))

    def test_collect_only_configured_keys_and_no_network_for_others(self):
        calls = []
        opener = lambda req, timeout=None: calls.append(req.full_url) or _Resp(b'{"data": {"usage": 0, "limit": null}}')
        out = api_balance.collect({"GROQ_API_KEY": "g", "UCLI_API_KEY": "e", "ANTHROPIC_API_KEY": "a"},
                                  {"today_usd": 0.5, "cap_usd": 0, "pct": None}, opener)
        self.assertEqual(calls, [])                                  # ağa çıkılmadı
        self.assertEqual(out["api:Groq"]["reason"], "no_endpoint")
        self.assertEqual(out["api:Evren"]["checked_via"], "local")
        self.assertNotIn("api:OpenRouter", out)                      # anahtarı yok
        for v in out.values():
            self.assertNotIn('"g"', json.dumps(v))

    def test_collect_empty(self):
        self.assertEqual(api_balance.collect({}, None), {})
        self.assertEqual(api_balance.collect(None, None), {})
        self.assertEqual(api_balance.collect({"GROQ_API_KEY": "g"}, None)["api:Groq"]["reason"], "no_endpoint")


if __name__ == "__main__":
    unittest.main()

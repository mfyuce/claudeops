"""TBD#146: Grok/OpenRouter `/models` çekimi 24 sa önbellekli; hata 60 sn; hata olunca [] (çağıran datalist'e düşer).

Çalıştırma:  python3 py/tests/test_service_models_cache.py -v
"""
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_session_opts as uso  # noqa: E402


class _R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


class ServiceModelsCache(unittest.TestCase):
    def setUp(self):
        uso._MODELS_CACHE.clear()

    def tearDown(self):
        uso._MODELS_CACHE.clear()

    def test_ttl_is_24h(self):
        self.assertEqual(uso._MODELS_TTL, 86400.0)

    def test_success_cached_for_a_day(self):
        calls = []

        def opener(req, timeout=0):
            calls.append(req.full_url)
            return _R(json.dumps({"data": [{"id": "m1"}]}).encode())

        for svc in ("grok", "openrouter"):
            if svc not in uso.services():
                continue
            calls.clear()
            self.assertEqual(uso.service_models(svc, "K", opener=opener, now=lambda: 1000.0), ["m1"])
            self.assertEqual(uso.service_models(svc, "K", opener=opener, now=lambda: 1000.0 + 80000), ["m1"])
            self.assertEqual(len(calls), 1)
            uso.service_models(svc, "K", opener=opener, now=lambda: 1000.0 + 90000)
            self.assertEqual(len(calls), 2)

    def test_failure_returns_empty_and_retries_after_60s(self):
        n = []

        def bad(req, timeout=0):
            n.append(1)
            raise OSError("down")

        svc = "grok" if "grok" in uso.services() else next(s for s in uso.services() if s != "evren")
        self.assertEqual(uso.service_models(svc, "K", opener=bad, now=lambda: 0.0), [])
        uso.service_models(svc, "K", opener=bad, now=lambda: 30.0)
        self.assertEqual(len(n), 1)
        uso.service_models(svc, "K", opener=bad, now=lambda: 61.0)
        self.assertEqual(len(n), 2)


if __name__ == "__main__":
    unittest.main()

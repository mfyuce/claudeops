"""ucli uç noktası ayarlanabilir (TODO "ucli sadece Evren'e sabit", 2026-10-20): `ucli_endpoint` ayarı model listesi
çekmeyi ve yeni oturumların `--endpoint`ini belirler; boş/geçersiz = Evren. Gerçek settings.json'a ve ağa DOKUNMAZ."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import settings  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


class UcliEndpointTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        p = mock.patch.object(settings, "SETTINGS_JSON", os.path.join(self.dir.name, "settings.json"))
        p.start()
        self.addCleanup(p.stop)

    def test_default_is_evren(self):
        self.assertEqual(settings.ucli_endpoint(), "")
        self.assertEqual(up.endpoint(), up.DEFAULT_ENDPOINT)

    def test_custom_valid_endpoint_wins_and_trailing_slash_dropped(self):
        settings.save_settings({"ucli_endpoint": "https://api.example.com/v1/"})
        self.assertEqual(up.endpoint(), "https://api.example.com/v1")

    def test_invalid_endpoint_falls_back_and_empty_clears(self):
        for bad in ("ftp://x/v1", "api.example.com", "https://a b/v1"):
            settings.save_settings({"ucli_endpoint": bad})
            self.assertEqual(up.endpoint(), up.DEFAULT_ENDPOINT, bad)
        settings.save_settings({"ucli_endpoint": "http://localhost:8000/v1"})
        self.assertEqual(up.endpoint(), "http://localhost:8000/v1")
        settings.save_settings({"ucli_endpoint": ""})
        self.assertEqual(up.endpoint(), up.DEFAULT_ENDPOINT)

    def test_model_list_fetch_uses_configured_endpoint(self):
        settings.save_settings({"ucli_endpoint": "http://localhost:8000/v1"})
        seen = []

        class _Resp:
            def read(self):
                return b'{"data": []}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(req, timeout=0):
            seen.append(req.full_url)
            return _Resp()

        with mock.patch.object(up, "byok_env_for", lambda cli: {"UCLI_API_KEY": "k"}), \
                mock.patch.object(up.urllib.request, "urlopen", fake_open):
            up._fetch_live_models()
        self.assertEqual(seen, ["http://localhost:8000/v1/models"])


if __name__ == "__main__":
    unittest.main()

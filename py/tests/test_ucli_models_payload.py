"""TBD#373 (4): ucli `/models` yanıtı nesne değilse (ya da `data` liste değilse) istisna yok: statik yedeğe düşülür."""
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import ucli_provider as up  # noqa: E402


class ModelsPayloadTest(unittest.TestCase):
    def _fetch(self, body: bytes):
        with mock.patch.object(up, "byok_env_for", return_value={"UCLI_API_KEY": "k"}), \
                mock.patch.object(up, "endpoint", return_value="http://127.0.0.1:1/v1"), \
                mock.patch.object(up.urllib.request, "urlopen", return_value=io.BytesIO(body)):
            return up._fetch_live_models()

    def test_non_object_or_non_list_payload_returns_none(self):
        for body in (b"[]", b'[{"id": "m", "task": "chat"}]', b'"x"', b"5", b"null", b"true",
                     b'{"data": 5}', b'{"data": null}', b'{"data": true}'):
            with self.subTest(body=body):
                self.assertIsNone(self._fetch(body))

    def test_valid_payload_still_works(self):
        with mock.patch.object(up, "_LIVE_CAPS", {}):
            self.assertEqual(self._fetch(b'{"data": [{"id": "m", "task": "chat"}]}'), ["m"])


if __name__ == "__main__":
    unittest.main()

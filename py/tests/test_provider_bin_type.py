"""TBD#373 (1): `settings.json`de `provider_bin.<cli>` metin değilse (elle düzenleme) yok sayılır; spawn yolu düşmez."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings, ucli_client  # noqa: E402

BAD = (5, None, True, ["/x"], {"a": 1}, 1.5)


class ProviderBinTypeTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.path = os.path.join(d.name, "settings.json")
        p = mock.patch.object(settings, "SETTINGS_JSON", self.path)
        p.start()
        self.addCleanup(p.stop)

    def _write(self, cli, value):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"provider_bin": {cli: value}}, f)

    def test_resolved_binary_ignores_non_string_override(self):
        for value in BAD:
            with self.subTest(value=value):
                self._write("claude", value)
                with mock.patch.object(settings.shutil, "which", return_value="/usr/bin/claude"):
                    self.assertEqual(settings.resolved_binary("claude"), "/usr/bin/claude")

    def test_ucli_resolve_binary_ignores_non_string_override(self):
        for value in BAD:
            with self.subTest(value=value):
                self._write("ucli", value)
                with mock.patch.dict(os.environ, {"UCLI_BIN": "/env/ucli"}):
                    self.assertEqual(ucli_client.resolve_binary(), "/env/ucli")


if __name__ == "__main__":
    unittest.main()

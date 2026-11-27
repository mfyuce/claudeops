"""ucli ikilisi UTF-8 olmayan çıktı verirse kontrol kaydı istisna atmaz: yoklama yalnız çıkış koduna bakar (doğrulama
atlanmaz), okunamayan doğrulama çıktısı kaydı reddeder."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_checks as uck  # noqa: E402


class NonUtf8Binary(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        p = mock.patch.object(uck, "ROOT", os.path.join(d.name, "ucli_checks"))
        p.start()
        self.addCleanup(p.stop)

    def binary(self, body):
        path = os.path.join(self.dir, "ucli")
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return path

    def test_probe_with_non_utf8_output_still_reports_support(self):
        self.assertTrue(uck.binary_supports_checks(self.binary("printf '\\377'; printf '\\376' >&2")))
        self.assertFalse(uck.binary_supports_checks(self.binary("printf '\\377' >&2; exit 2")))

    def test_unreadable_validation_output_rejects_and_writes_nothing(self):
        for body in ("printf '\\377'", "echo '{\"ok\": true}'; printf '\\377' >&2"):
            with self.subTest(body=body):
                ok, why = uck.save_registry({"check": [uck.TEMPLATES["git log"]]}, binary=self.binary(body))
                self.assertFalse(ok)
                self.assertIn("UnicodeDecodeError", why)
                self.assertFalse(os.path.exists(uck.registry_path()))
                self.assertEqual([n for n in os.listdir(uck.ROOT) if n.startswith(".validate-")], [])


if __name__ == "__main__":
    unittest.main()

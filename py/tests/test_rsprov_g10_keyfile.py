"""rs/prov G10 aday 5: açılamayan (izin) ucli anahtar dosyası "yok" sayılıp miras ortam anahtarıyla sürülmez. İki tarafta
düzeldi (Rust `real/oneshot.rs`, `real_oneshot::an_unreadable_key_file_is_refused_not_treated_as_missing`).

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_g10_keyfile.py
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import get_provider, ucli_provider  # noqa: E402
from claudeops.providers.base import OneshotError  # noqa: E402


class KeyFileTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(prefix="cops-keyfile-")
        self.addCleanup(d.cleanup)
        self.d = d.name
        self.key_file = os.path.join(self.d, "ucli_api_key")
        self.calls = []
        for p in (mock.patch.object(ucli_provider, "_API_KEY_FILE", self.key_file),
                  mock.patch.object(ucli_provider, "byok_env_for", lambda cli: {}),
                  mock.patch.object(ucli_provider, "ucli_chat_once", lambda root, prompt, **kw: self.calls.append(kw) or {"answer": "x"})):
            p.start()
            self.addCleanup(p.stop)

    @unittest.skipIf(os.geteuid() == 0, "root izin denetimini atlar")
    def test_unreadable_key_file_is_refused_not_treated_as_missing(self):
        with open(self.key_file, "w") as f:
            f.write("sk-gizli")
        os.chmod(self.key_file, 0)
        with self.assertRaises(OneshotError) as c:
            get_provider("ucli").oneshot("p", None, os.path.join(self.d, "cwd"), timeout=10)
        self.assertIn("açılamadı", str(c.exception))
        self.assertEqual(self.calls, [])        # miras ortam anahtarıyla sürmedi

    def test_missing_file_still_means_no_key(self):
        self.assertEqual(get_provider("ucli").oneshot("p", None, os.path.join(self.d, "cwd"), timeout=10), "x")
        self.assertEqual(self.calls[0]["api_key"], None)


if __name__ == "__main__":
    unittest.main()

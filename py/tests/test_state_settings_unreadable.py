"""TBD#383 (1): `settings.json` okunamıyorken kayıt, dosyayı varsayılanlarla ezmesin."""
import builtins
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import atomic_json as aj  # noqa: E402
from claudeops import settings  # noqa: E402


class SaveWhenUnreadable(unittest.TestCase):
    def test_save_is_refused_and_file_kept(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            body = json.dumps({"byok": {"ucli": {"ANAHTAR": "deger"}}, "steward_persona_text": "x"})
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            real_open = builtins.open

            def failing(file, mode="r", *a, **k):
                if str(file) == path and "r" in mode:
                    raise OSError(24, "Too many open files")
                return real_open(file, mode, *a, **k)

            with mock.patch.object(settings, "SETTINGS_JSON", path), mock.patch.dict(settings._LOAD_CACHE, {"sig": None}):
                with mock.patch("builtins.open", failing):
                    with self.assertRaises(aj.LockError):
                        settings.save_settings({"theme": "dark"})
            with real_open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), body)

    def test_missing_file_still_saves(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            with mock.patch.object(settings, "SETTINGS_JSON", path), mock.patch.dict(settings._LOAD_CACHE, {"sig": None}):
                self.assertEqual(settings.save_settings({"theme": "dark"})["theme"], "dark")
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()

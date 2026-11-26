"""TBD#374 (a) S2/S7: okunamayan/bozuk settings.json."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name

    def patch(self, obj, name, value):
        p = mock.patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)


class SettingsReadFailures(_Tmp):
    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.d, "settings.json")
        self.patch(settings, "SETTINGS_JSON", self.path)
        self.patch(settings, "_LOAD_CACHE", {"sig": None, "val": None})
        self.patch(settings, "_LAST_BACKEND", {})

    def _write(self, raw: bytes):
        with open(self.path + ".new", "wb") as f:
            f.write(raw)
        os.replace(self.path + ".new", self.path)

    def test_s2_bad_utf8_gives_defaults(self):
        self._write(b'{"theme": "\xff"}')
        self.assertEqual(settings.load_settings()["store_backend"], "files")

    def test_s2_corrupt_keeps_last_good_store_backend_only(self):
        for bad in (b"\xff\xfe", b"{yarim", b"[1]"):
            with self.subTest(bad=bad):
                self._write(b'{"store_backend": "db", "spawn_nice": "3"}')
                self.assertEqual(settings.load_settings()["store_backend"], "db")
                self._write(bad)
                got = settings.load_settings()
                self.assertEqual(got["store_backend"], "db")
                self.assertEqual(got["spawn_nice"], settings.DEFAULT_SETTINGS["spawn_nice"])

    def test_s7_io_error_is_not_cached(self):
        self._write(b'{"store_backend": "db", "spawn_nice": "3"}')
        with mock.patch("builtins.open", side_effect=PermissionError("yok")):
            got = settings.load_settings()
        self.assertEqual(got["spawn_nice"], settings.DEFAULT_SETTINGS["spawn_nice"])
        self.assertEqual(settings.load_settings()["spawn_nice"], "3")     # dosya değişmeden yeniden okunur

    def test_deleted_file_is_plain_default(self):
        self._write(b'{"store_backend": "db"}')
        settings.load_settings()
        os.remove(self.path)
        self.assertEqual(settings.load_settings()["store_backend"], "files")


if __name__ == "__main__":
    unittest.main()

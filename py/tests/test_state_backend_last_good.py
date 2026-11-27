"""TBD#374 (a) S2/S7: settings.json bozulur/okunamazsa `statedocs.backend()` canlı kipi sessizce `files`a çevirmez."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import paths, statedocs  # noqa: E402


class BackendLastGood(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.path = os.path.join(d.name, "settings.json")
        for p in (mock.patch.object(paths, "CLAUDEOPS_DIR", d.name),
                  mock.patch.dict(statedocs._CACHE, {"at": 0.0, "mode": "files"}, clear=True),
                  mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": ""})):
            p.start()
            self.addCleanup(p.stop)

    def _backend(self, raw=None):
        if raw is not None:
            with open(self.path, "wb") as f:
                f.write(raw)
        statedocs._CACHE["at"] = 0.0
        return statedocs.backend()

    def test_corrupt_or_unreadable_keeps_last_good(self):
        self.assertEqual(self._backend(b'{"store_backend": "db"}'), "db")
        for bad in (b"\xff", b"{yarim", b"[1]"):
            with self.subTest(bad=bad):
                self.assertEqual(self._backend(bad), "db")
        with mock.patch("builtins.open", side_effect=PermissionError("yok")):
            self.assertEqual(self._backend(), "db")

    def test_missing_file_is_files(self):
        self._backend(b'{"store_backend": "db"}')
        os.remove(self.path)
        self.assertEqual(self._backend(), "files")

    def test_corrupt_from_start_is_files(self):
        self.assertEqual(self._backend(b"{yarim"), "files")


if __name__ == "__main__":
    unittest.main()

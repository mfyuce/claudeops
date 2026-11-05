"""DATA-02: bozuk settings.json ilk yazimda sessizce ezilmez: ham dosya .corrupt-<sha8> olarak yedeklenir.
SETTINGS_JSON gecici dosyaya yonlendirilir (gercek ayar dosyasina DOKUNULMAZ)."""
import glob
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings, diaglog  # noqa: E402


class CorruptBackupTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "settings.json")
        self.logs = []
        for patcher in (mock.patch.object(settings, "SETTINGS_JSON", self.p),
                        mock.patch.object(diaglog, "diag_log", lambda ev, **k: self.logs.append((ev, k)))):
            patcher.start()
            self.addCleanup(patcher.stop)
        sd = mock.patch("claudeops.statedocs.write_json",
                        lambda name, path, obj, mode=0o600, writer=None: writer(path, obj, mode=mode) if writer else None)
        sd.start()
        self.addCleanup(sd.stop)

    def _write(self, raw):
        with open(self.p, "w", encoding="utf-8") as f:
            f.write(raw)

    def test_corrupt_file_backed_up_before_write(self):
        self._write('{"byok": {"x": "SECRET"')          # yarim JSON
        settings.save_settings({"lang": "tr"})
        backups = glob.glob(self.p + ".corrupt-*")
        self.assertEqual(len(backups), 1)
        with open(backups[0], encoding="utf-8") as f:
            self.assertIn("SECRET", f.read())
        self.assertEqual(oct(os.stat(backups[0]).st_mode & 0o777), "0o600")
        self.assertEqual(self.logs[0][0], "settings_corrupt_backup")

    def test_valid_and_missing_file_not_backed_up(self):
        settings.save_settings({"lang": "tr"})            # dosya yok
        self._write(json.dumps({"lang": "en"}))
        settings.save_settings({"lang": "tr"})
        self.assertEqual(glob.glob(self.p + ".corrupt-*"), [])

    def test_non_object_json_is_corrupt(self):
        self._write("[1, 2]")
        settings.save_settings({"lang": "tr"})
        self.assertEqual(len(glob.glob(self.p + ".corrupt-*")), 1)


if __name__ == "__main__":
    unittest.main()

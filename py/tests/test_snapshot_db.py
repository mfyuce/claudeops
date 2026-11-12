"""Göç Adım E: snapshots `db` kipinde DB-tek-kaynak; bozuk dosya DB'yi ezmez, yazımda yedeklenir."""
import glob
import os
import shutil
import tempfile
import unittest
from unittest import mock

from claudeops import snapshot, statedocs
from claudeops.store import Store


class SnapshotDbTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.d, ignore_errors=True))
        self.st = Store(os.path.join(self.d, "t.db"))
        self.path = os.path.join(self.d, "snapshots.json")
        for p in (mock.patch.object(snapshot, "SNAPSHOTS_JSON", self.path),
                  mock.patch.object(snapshot, "SNAPSHOT_JSON", os.path.join(self.d, "last_snapshot.json")),
                  mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.d),
                  mock.patch("claudeops.store.default_store", lambda: self.st)):
            p.start(); self.addCleanup(p.stop)

    def _mode(self, m):
        p = mock.patch.object(statedocs, "backend", lambda: m)
        p.start(); self.addCleanup(p.stop)

    def test_db_ready(self):
        self.assertTrue(statedocs.db_ready("snapshots"))

    def test_db_wins_over_corrupt_file_and_backs_up_on_write(self):
        self._mode("db")
        self.st.set_doc("snapshots", [{"saved_at": 1.0, "kind": "manual", "sessions": []}])
        with open(self.path, "w") as f:
            f.write("{bozuk")
        self.assertEqual(len(snapshot._load_all()), 1)               # DB kazanır
        snapshot._backup_if_corrupt()
        self.assertEqual(len(glob.glob(self.path + ".corrupt-*")), 1)   # ham dosya yedeklendi

    def test_db_missing_file_missing_legacy_migrates_once(self):
        self._mode("db")
        self.assertEqual(snapshot._load_all(), [])

    def test_corrupt_file_without_db_is_empty_not_legacy(self):
        self._mode("db")
        with open(os.path.join(self.d, "last_snapshot.json"), "w") as f:
            f.write('{"saved_at": 5, "sessions": [{"name": "x"}]}')
        with open(self.path, "w") as f:
            f.write("{bozuk")
        self.assertEqual(snapshot._load_all(), [])

    def test_db_non_list_is_empty(self):
        self._mode("db")
        self.st.set_doc("snapshots", {"x": 1})
        self.assertEqual(snapshot._load_all(), [])


if __name__ == "__main__":
    unittest.main()

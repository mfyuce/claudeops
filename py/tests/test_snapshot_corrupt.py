"""Bozuk snapshots.json: sonraki save_snapshot geçmişin TAMAMINI sessizce silmesin (ham dosya yedeklenir)."""
import glob
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import snapshot  # noqa: E402


class CorruptSnapshotsTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.f = os.path.join(d, "snapshots.json")
        for name, val in (("SNAPSHOTS_JSON", self.f), ("SNAPSHOT_JSON", os.path.join(d, "last_snapshot.json"))):
            p = mock.patch.object(snapshot, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_corrupt_file_backed_up_before_overwrite(self):
        raw = '[{"saved_at": 1, "kind": "manual", "sessions": [{"name": "eski"}]},'      # kesik
        open(self.f, "w").write(raw)
        snapshot.save_snapshot([{"name": "yeni"}], kind="manual")
        bk = glob.glob(self.f + ".corrupt-*")
        self.assertEqual(len(bk), 1)
        self.assertEqual(open(bk[0]).read(), raw)
        self.assertEqual([s["sessions"][0]["name"] for s in snapshot._load_all()], ["yeni"])
        snapshot.save_snapshot([{"name": "yeni2"}], kind="manual")                     # sağlam dosya: yeni yedek yok
        self.assertEqual(len(glob.glob(self.f + ".corrupt-*")), 1)

    def test_non_list_json_also_backed_up(self):
        open(self.f, "w").write('{"x": 1}')
        snapshot.save_snapshot([{"name": "a"}], kind="manual")
        self.assertEqual(len(glob.glob(self.f + ".corrupt-*")), 1)

    def test_non_dict_items_filtered(self):
        open(self.f, "w").write('[1, "x", null, {"saved_at": 5, "kind": "manual", "sessions": []}]')
        got = snapshot._load_all()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["saved_at"], 5)
        self.assertIsNotNone(snapshot.get_snapshot(5))
        self.assertEqual(len(snapshot.list_snapshots()), 1)

    def test_legacy_not_resurrected_when_snapshots_corrupt(self):
        with open(snapshot.SNAPSHOT_JSON, "w") as f:
            f.write('{"saved_at": 5.0, "sessions": [{"name": "legacy"}]}')
        open(self.f, "w").write("{bozuk")
        self.assertEqual(snapshot._load_all(), [])
        self.assertEqual(snapshot.load_latest_snapshot()["sessions"], [])

    def test_legacy_migrates_only_when_snapshots_missing(self):
        with open(snapshot.SNAPSHOT_JSON, "w") as f:
            f.write('{"saved_at": 5.0, "sessions": [{"name": "legacy"}]}')
        got = snapshot._load_all()
        self.assertEqual([s["sessions"][0]["name"] for s in got], ["legacy"])

    def test_missing_or_empty_file_no_backup(self):
        snapshot.save_snapshot([{"name": "a"}], kind="manual")
        os.remove(self.f)
        open(self.f, "w").write("")
        snapshot.save_snapshot([{"name": "b"}], kind="manual")
        self.assertEqual(glob.glob(self.f + ".corrupt-*"), [])


if __name__ == "__main__":
    unittest.main()

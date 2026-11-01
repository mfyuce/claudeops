"""Eşzamanlı save_snapshot: oku-değiştir-yaz kilit altında, hiçbir girdi kaybolmaz."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import snapshot  # noqa: E402


class ConcurrentSnapshotTest(unittest.TestCase):
    def test_parallel_manual_saves_all_kept(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(snapshot, "SNAPSHOTS_JSON", os.path.join(d, "snapshots.json")), \
                mock.patch.object(snapshot, "SNAPSHOT_JSON", os.path.join(d, "last_snapshot.json")):
            n = 12
            ts = [threading.Thread(target=snapshot.save_snapshot, args=([{"name": f"s{i}"}],), kwargs={"kind": "manual"})
                  for i in range(n)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            names = sorted(e["sessions"][0]["name"] for e in snapshot._load_all())
            self.assertEqual(names, sorted(f"s{i}" for i in range(n)))


if __name__ == "__main__":
    unittest.main()

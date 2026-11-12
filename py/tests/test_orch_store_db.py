"""Göç Adım D: orchestration/* belgeleri `db` kipinde DB-tek-kaynak, dual'de dosya doğruluk kaynağı."""
import os
import tempfile
import unittest
from unittest import mock

from claudeops import orch_store, statedocs
from claudeops.store import Store


class OrchStoreDbTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.d, ignore_errors=True))
        self.st = Store(os.path.join(self.d, "t.db"))
        orch = os.path.join(self.d, "orchestration")
        for p, v in [(mock.patch.object(orch_store, "ORCH_DIR", orch), 0),
                     (mock.patch.object(orch_store, "RUNS_DIR", os.path.join(orch, "runs")), 0),
                     (mock.patch.object(orch_store, "DRAFT_JSON", os.path.join(orch, "draft.json")), 0),
                     (mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.d), 0),
                     (mock.patch("claudeops.store.default_store", lambda: self.st), 0)]:
            p.start(); self.addCleanup(p.stop)

    def _mode(self, m):
        p = mock.patch.object(statedocs, "backend", lambda: m)
        p.start(); self.addCleanup(p.stop)

    def test_prefix_is_db_ready(self):
        self.assertTrue(statedocs.db_ready("orchestration/runs/r1"))
        self.assertTrue(statedocs.db_ready("orchestration/draft"))

    def test_db_mode_load_from_db_when_file_missing_or_stale(self):
        self._mode("db")
        orch_store.save_run({"id": "r20260101_000000_ab", "x": 1})
        path = orch_store._run_path("r20260101_000000_ab")
        os.remove(path)                                   # ayna silindi: DB yine de okunur
        self.assertEqual(orch_store.load_run("r20260101_000000_ab")["x"], 1)
        with open(path, "w") as f:                        # elle bayat/yanlış dosya: DB kazanır
            f.write('{"id": "r20260101_000000_ab", "x": 99}')
        self.assertEqual(orch_store.load_run("r20260101_000000_ab")["x"], 1)

    def test_dual_mode_file_wins(self):
        self._mode("dual")
        orch_store.save_draft([{"a": 1}])
        with open(orch_store.DRAFT_JSON, "w") as f:
            f.write('{"participants": [{"a": 2}]}')
        self.assertEqual(orch_store.load_draft(), [{"a": 2}])

    def test_list_runs_uses_mirror_in_db_mode(self):
        self._mode("db")
        orch_store.save_run({"id": "r20260101_000000_aa"})
        orch_store.save_run({"id": "r20260102_000000_bb"})
        self.assertEqual([r["id"] for r in orch_store.list_runs()], ["r20260102_000000_bb", "r20260101_000000_aa"])

    def test_corrupt_file_in_db_mode_returns_db(self):
        self._mode("db")
        orch_store.save_draft([{"a": 1}])
        with open(orch_store.DRAFT_JSON, "w") as f:
            f.write("{bozuk")
        self.assertEqual(orch_store.load_draft(), [{"a": 1}])


if __name__ == "__main__":
    unittest.main()

"""db kipinde bozuk `instances.json` aynası: DB satırı sağlamsa okuma/yazma ondan sürer, ayna yedeklenip yenilenir.
DB doğruluğu kesin değilse (satır yok, DB okunamıyor, son DB yazımı başarısız, belge bozuk) yine reddedilir."""
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import instances, statedocs as sd, store as S  # noqa: E402

BAD = "{yarim"


class CorruptMirror(unittest.TestCase):
    mode = "db"

    def setUp(self):
        d = tempfile.mkdtemp(prefix="cops-inst-")
        self.addCleanup(shutil.rmtree, d, True)
        self.path = os.path.join(d, "instances.json")
        self.st = S.Store(os.path.join(d, "t.db"))
        self.addCleanup(self.st.close)
        for p in (mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": self.mode,
                                               "CLAUDEOPS_DIAG_LOG": os.path.join(d, "diag.log")}),
                  mock.patch.object(S, "default_store", lambda: self.st),
                  mock.patch("claudeops.paths.CLAUDEOPS_DIR", d),
                  mock.patch.object(instances, "INSTANCES_JSON", self.path),
                  mock.patch.object(instances, "_LOCK_PATH", self.path + ".lock"),
                  mock.patch.object(instances, "_cache_key", None),
                  mock.patch.object(instances, "_cache", {}),
                  mock.patch.object(instances, "_db_cache", None),
                  mock.patch.object(sd, "_DIRTY", set())):
            p.start()
            self.addCleanup(p.stop)

    def corrupt(self, raw=BAD):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(raw)

    def raw(self, path=None):
        with open(path or self.path, encoding="utf-8") as f:
            return f.read()

    def record(self, name):
        instances.record_instance(name, blueprint=None, cwd="/c", cli="claude", model="m", origin="t")

    def refused(self):
        self.assertEqual(instances.load_instances(), {})
        with self.assertRaises(instances.InstancesCorrupt):
            self.record("yeni")
        self.assertEqual(self.raw(), BAD)

    def test_db_row_serves_reads_and_writes_mirror_backed_up(self):
        self.record("a")
        self.corrupt()
        instances._db_cache = None
        self.assertEqual(set(instances.load_instances()), {"a"})
        self.record("b")
        self.assertEqual(set(self.st.get_doc("instances")["instances"]), {"a", "b"})
        self.assertEqual(set(json.loads(self.raw())["instances"]), {"a", "b"})
        copies = glob.glob(self.path + ".corrupt-*")
        self.assertEqual(len(copies), 1)
        self.assertEqual(self.raw(copies[0]), BAD)
        self.assertEqual(os.stat(copies[0]).st_mode & 0o777, 0o600)

    def test_no_row_refused(self):
        self.corrupt()
        self.refused()

    def test_dirty_refused(self):
        self.record("a")
        self.corrupt()
        sd._DIRTY.add("instances")
        self.refused()

    def test_db_unreadable_refused(self):
        self.record("a")
        self.corrupt()
        instances._db_cache = None
        with mock.patch.object(self.st, "get_doc", side_effect=RuntimeError("db")):
            self.refused()

    def test_bad_db_doc_refused(self):
        self.st.set_doc("instances", {"version": 1, "instances": []})
        self.corrupt()
        self.refused()


class CorruptMirrorDual(CorruptMirror):
    """dual kipte dosya doğruluk kaynağı: bozuksa reddedilir."""
    mode = "dual"

    def test_db_row_serves_reads_and_writes_mirror_backed_up(self):
        self.record("a")
        self.corrupt()
        self.refused()


if __name__ == "__main__":
    unittest.main()

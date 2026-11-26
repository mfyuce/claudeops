"""`load_instances`/`get_instance` sonucu değiştirilirse (iç içe alanlar dahil) önbellek kirlenmez (db ve files kipi)."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import instances, statedocs as sd, store as S  # noqa: E402


class CacheCopy(unittest.TestCase):
    def run_mode(self, mode):
        d = tempfile.mkdtemp(prefix="cops-inst-")
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "instances.json")
        st = S.Store(os.path.join(d, "t.db"))
        self.addCleanup(st.close)
        for p in (mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": mode,
                                               "CLAUDEOPS_DIAG_LOG": os.path.join(d, "diag.log")}),
                  mock.patch.object(S, "default_store", lambda: st),
                  mock.patch("claudeops.paths.CLAUDEOPS_DIR", d),
                  mock.patch.object(instances, "INSTANCES_JSON", path),
                  mock.patch.object(instances, "_LOCK_PATH", path + ".lock"),
                  mock.patch.object(instances, "_cache_key", None),
                  mock.patch.object(instances, "_cache", {}),
                  mock.patch.object(instances, "_db_cache", None),
                  mock.patch.object(sd, "_DIRTY", set())):
            p.start()
            self.addCleanup(p.stop)
        instances.record_instance("a", blueprint=None, cwd="/c", cli="claude", model="m", origin="t",
                                  cli_opts={"x": [1]})
        for read in (lambda: instances.load_instances()["a"], lambda: instances.get_instance("a")):
            for _ in range(2):                  # ilki önbelleği doldurur, ikincisi isabet
                rec = read()
                self.assertEqual((rec["cwd"], rec["cli_opts"]), ("/c", {"x": [1]}))
                rec["cwd"] = "/kirli"
                rec["cli_opts"]["x"].append(2)
        self.assertIsNone(instances.get_instance("yok"))

    def test_db(self):
        self.run_mode("db")

    def test_files(self):
        self.run_mode("files")


if __name__ == "__main__":
    unittest.main()

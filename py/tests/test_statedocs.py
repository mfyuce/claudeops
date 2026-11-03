import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import json, tempfile, unittest
from unittest import mock
from claudeops import statedocs as sd, store as S


class StateDocsTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cops-sd-")
        self.path = os.path.join(self.d, "q.json")
        self.st = S.Store(os.path.join(self.d, "t.db"))
        self.p = [mock.patch.object(S, "default_store", lambda: self.st)]
        [p.start() for p in self.p]

    def tearDown(self):
        [p.stop() for p in self.p]; self.st.close()
        os.environ.pop("CLAUDEOPS_STORE_BACKEND", None)

    def mode(self, m):
        os.environ["CLAUDEOPS_STORE_BACKEND"] = m

    def test_files_mode_never_touches_db(self):
        self.mode("files"); sd.write_json("q", self.path, {"a": 1})
        self.assertEqual(json.load(open(self.path)), {"a": 1})
        self.assertEqual(self.st.list_docs(), [])
        self.assertEqual(sd.read_json("q", self.path), {"a": 1})

    def test_dual_writes_both_and_reads_db(self):
        self.mode("dual"); sd.write_json("q", self.path, {"a": 2})
        self.assertEqual(json.load(open(self.path)), {"a": 2}); self.assertEqual(self.st.get_doc("q"), {"a": 2})
        self.st.set_doc("q", {"a": 3}); self.assertEqual(sd.read_json("q", self.path), {"a": 3})

    def test_lazy_import_from_file(self):
        json.dump({"old": 1}, open(self.path, "w"))
        self.mode("dual"); self.assertEqual(sd.read_json("q", self.path), {"old": 1})
        self.assertEqual(self.st.get_doc("q"), {"old": 1})

    def test_db_mode_writes_only_db_and_default(self):
        self.mode("db"); sd.write_json("q", self.path, {"a": 4})
        self.assertFalse(os.path.exists(self.path)); self.assertEqual(sd.read_json("q", self.path), {"a": 4})
        self.assertEqual(sd.read_json("none", self.path + "x", "dflt"), "dflt")

    def test_db_failure_falls_back_to_file(self):
        json.dump({"f": 1}, open(self.path, "w"))
        self.mode("dual")
        with mock.patch.object(S, "default_store", side_effect=RuntimeError("boom")):
            self.assertEqual(sd.read_json("q", self.path), {"f": 1})
            sd.write_json("q", self.path, {"f": 2})          # dual: DB düştü ama dosya yazıldı
        self.assertEqual(json.load(open(self.path)), {"f": 2})
        self.mode("db")
        with mock.patch.object(S, "default_store", side_effect=RuntimeError("boom")):
            sd.write_json("q", self.path, {"f": 3})          # db: DB düştü, veri kaybolmasın -> dosya
        self.assertEqual(json.load(open(self.path)), {"f": 3})

    def test_backend_from_settings_and_default(self):
        os.environ.pop("CLAUDEOPS_STORE_BACKEND", None)
        with mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.d):
            sd._CACHE.update(at=0.0); self.assertEqual(sd.backend(), "files")
            json.dump({"store_backend": "dual"}, open(os.path.join(self.d, "settings.json"), "w"))
            sd._CACHE.update(at=0.0); self.assertEqual(sd.backend(), "dual")


if __name__ == "__main__":
    unittest.main()

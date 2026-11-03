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
        self.p = [mock.patch.object(S, "default_store", lambda: self.st), mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.d)]
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
        sd._CACHE.update(at=0.0); self.assertEqual(sd.backend(), "files")
        json.dump({"store_backend": "dual"}, open(os.path.join(self.d, "settings.json"), "w"))
        sd._CACHE.update(at=0.0); self.assertEqual(sd.backend(), "dual")

    def test_outside_claudeops_dir_is_files_only(self):
        other = tempfile.mkdtemp(prefix="cops-sd-other-"); path = os.path.join(other, "x.json")
        self.mode("db"); sd.write_json("x", path, {"a": 1})
        self.assertEqual(json.load(open(path)), {"a": 1}); self.assertEqual(self.st.list_docs(), [])
        sd.mirror_log("s", path, {"e": 1}); self.assertEqual(self.st.tail_log("s"), [])

    def test_file_truth_dual_heals_drift_and_survives_hand_edit(self):
        self.mode("dual"); sd.write_json("h", self.path, [{"name": "a"}])
        json.dump([{"name": "a"}, {"name": "b"}], open(self.path, "w"))      # elle düzenleme
        self.assertEqual(sd.read_json("h", self.path, file_truth=True), [{"name": "a"}, {"name": "b"}])
        self.assertEqual(self.st.get_doc("h"), [{"name": "a"}, {"name": "b"}])   # DB dosyaya uydu
        os.remove(self.path)                                                  # dosya yoksa DB'den
        self.assertEqual(sd.read_json("h", self.path, file_truth=True), [{"name": "a"}, {"name": "b"}])

    def test_mirror_log_modes(self):
        p = os.path.join(self.d, "diag.log")
        self.mode("files"); sd.mirror_log("diag", p, {"e": 1}); self.assertEqual(self.st.tail_log("diag"), [])
        self.mode("dual"); sd.mirror_log("diag", p, {"e": 2}); self.assertEqual([r[2] for r in self.st.tail_log("diag")], [{"e": 2}])
        with mock.patch.object(S, "default_store", side_effect=RuntimeError("x")):
            sd.mirror_log("diag", p, {"e": 3})                                # hata yutulur, yükseltmez


if __name__ == "__main__":
    unittest.main()

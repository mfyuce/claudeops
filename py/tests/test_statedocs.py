import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import json, tempfile, unittest
from unittest import mock
from claudeops import statedocs as sd, store as S


class StateDocsTests(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"CLAUDEOPS_DIAG_LOG": os.path.join(tempfile.mkdtemp(prefix="cops-sd-diag-"), "diag.log")}); self._env.start()
        self.d = tempfile.mkdtemp(prefix="cops-sd-")
        self.path = os.path.join(self.d, "q.json")
        self.st = S.Store(os.path.join(self.d, "t.db"))
        self.p = [mock.patch.object(S, "default_store", lambda: self.st), mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.d), mock.patch.object(sd, "DB_READY", {"q", "x", "h", "hosts"})]
        [p.start() for p in self.p]

    def tearDown(self):
        [p.stop() for p in self.p]; self.st.close(); self._env.stop()
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
        self.st.set_doc("q", {"a": 3})
        self.assertEqual(sd.read_json("q", self.path), {"a": 2})                      # dual: dosya doğruluk kaynağı
        self.assertEqual(sd.read_json("q", self.path, file_truth=False), {"a": 3})    # DB-önce istenirse

    def test_lazy_import_from_file(self):
        json.dump({"old": 1}, open(self.path, "w"))
        self.mode("dual"); self.assertEqual(sd.read_json("q", self.path), {"old": 1})
        self.assertEqual(self.st.get_doc("q"), {"old": 1})

    def test_db_mode_db_is_truth_file_is_mirror(self):
        self.mode("db"); sd.write_json("q", self.path, {"a": 4})
        self.assertEqual(json.load(open(self.path)), {"a": 4})                 # ayna (mtime/listdir tabanlı kod için)
        self.assertEqual(sd.read_json("q", self.path), {"a": 4})
        json.dump({"hand": 1}, open(self.path, "w"))                           # elle düzenleme: okuyucu dosyaya BAKMAZ
        self.assertEqual(sd.read_json("q", self.path), {"a": 4})
        self.assertEqual(sd.read_json("none", self.path + "x", "dflt"), "dflt")

    def test_db_mode_reader_mid_write_sees_db_no_drift(self):
        # dual'deki yarış: DB yazıldı, dosya henüz eski. db kipinde okuyucu yalnız DB'ye bakar: drift yok, geri alma yok.
        log = os.environ["CLAUDEOPS_DIAG_LOG"]
        self.mode("db"); sd.write_json("q", self.path, {"v": 1})
        self.st.set_doc("q", {"v": 2})                                          # yazar DB'yi güncelledi, dosya eski
        self.assertEqual(sd.read_json("q", self.path), {"v": 2})
        self.assertEqual(self.st.get_doc("q"), {"v": 2})
        self.assertNotIn("drift", open(log).read() if os.path.exists(log) else "")

    def test_db_write_failure_recovers_from_file_on_next_read(self):
        self.mode("db"); sd.write_json("q", self.path, {"v": 1})
        with mock.patch.object(self.st, "set_doc", side_effect=RuntimeError("locked")):
            sd.write_json("q", self.path, {"v": 2})                            # DB düştü -> dosya, belge kirli
        self.assertEqual(self.st.get_doc("q"), {"v": 1})
        self.assertEqual(sd.read_json("q", self.path), {"v": 2})               # dosyadan geri alınır
        self.assertEqual(self.st.get_doc("q"), {"v": 2}); self.assertNotIn("q", sd._DIRTY)

    def test_steward_prefix_is_db_ready(self):
        self.assertTrue(sd.db_ready("steward/questions")); self.assertTrue(sd.db_ready("steward/stewards/reviewer/findings"))
        self.assertFalse(sd.db_ready("settings")); self.assertFalse(sd.db_ready("instances"))
        self.mode("db"); self.assertEqual(sd._effective("settings"), "dual"); self.assertEqual(sd._effective("steward/state"), "db")

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

    def test_first_import_is_not_logged_as_drift(self):
        log = os.environ["CLAUDEOPS_DIAG_LOG"]
        json.dump({"old": 1}, open(self.path, "w"))                           # gölgeden önce yazılmış dosya
        self.mode("dual"); sd.read_json("q", self.path)
        txt = open(log).read() if os.path.exists(log) else ""
        self.assertIn("import q", txt); self.assertNotIn("drift q", txt)
        self.st.set_doc("q", {"zzz": 1}); json.dump({"old": 22}, open(self.path, "w"))  # gerçek ayrışma (boyut farklı: mtime kaba olabilir)
        sd.read_json("q", self.path)
        self.assertIn("drift q", open(log).read())

    def test_dual_skips_db_compare_when_file_unchanged(self):
        self.mode("dual"); sd.write_json("q", self.path, {"a": 1})
        self.st.set_doc("q", {"zzz": 1})                      # DB bozuldu ama dosya imzası değişmedi -> karşılaştırma YOK
        self.assertEqual(sd.read_json("q", self.path), {"a": 1}); self.assertEqual(self.st.get_doc("q"), {"zzz": 1})
        json.dump({"a": 9}, open(self.path, "w"))             # dosya değişti -> eşitlenir
        self.assertEqual(sd.read_json("q", self.path), {"a": 9}); self.assertEqual(self.st.get_doc("q"), {"a": 9})

    def test_mirror_log_modes(self):
        p = os.path.join(self.d, "diag.log")
        self.mode("files"); sd.mirror_log("diag", p, {"e": 1}); self.assertEqual(self.st.tail_log("diag"), [])
        self.mode("dual"); sd.mirror_log("diag", p, {"e": 2}); self.assertEqual([r[2] for r in self.st.tail_log("diag")], [{"e": 2}])
        with mock.patch.object(S, "default_store", side_effect=RuntimeError("x")):
            sd.mirror_log("diag", p, {"e": 3})                                # hata yutulur, yükseltmez


if __name__ == "__main__":
    unittest.main()

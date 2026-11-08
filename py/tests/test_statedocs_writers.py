import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import json, tempfile, unittest
from unittest import mock
from claudeops import statedocs as sd, store as S, steward as sw, instances as ins


class WritersShadowTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cops-wr-")
        self.st = S.Store(os.path.join(self.d, "t.db"))
        self.ps = [mock.patch.object(S, "default_store", lambda: self.st), mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.d),
                   mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "dual", "CLAUDEOPS_DIAG_LOG": os.path.join(self.d, "diag.log")})]
        [p.start() for p in self.ps]
        sd._SYNCED.clear()

    def tearDown(self):
        [p.stop() for p in self.ps]; self.st.close()

    def test_name_for(self):
        self.assertEqual(sd.name_for(os.path.join(self.d, "steward", "stewards", "rev", "questions.json")), "steward/stewards/rev/questions")
        self.assertEqual(sd.name_for(os.path.join(self.d, "x.tsv")), "x.tsv")

    def test_steward_save_load_shadow(self):
        p = os.path.join(self.d, "steward", "questions.json")
        sw._save_json(p, [{"id": 1}])
        self.assertEqual(json.load(open(p)), [{"id": 1}]); self.assertEqual(self.st.get_doc("steward/questions"), [{"id": 1}])
        self.assertEqual(sw._load_json(p, []), [{"id": 1}])

    def test_steward_corrupt_backup_kept_and_db_recovers(self):
        p = os.path.join(self.d, "steward", "state.json")
        sw._save_json(p, {"a": 1})
        open(p, "w").write("{bozuk")
        sd._SYNCED.clear()
        self.assertEqual(sw._load_json(p, {}), {"a": 1})                          # DB kopyası kurtarır
        self.assertTrue([n for n in os.listdir(os.path.dirname(p)) if ".corrupt-" in n])   # kanıt yedeği duruyor

    def test_non_ready_docs_stay_file_even_in_db_mode(self):
        p = os.path.join(self.d, "instances.json")
        with mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "db"}):
            sw._save_json(p, {"a": 2})
            self.assertTrue(os.path.exists(p))                                    # okuyucusu bağlı değil: dosya yazılmaya devam
            self.assertEqual(self.st.get_doc("instances"), {"a": 2})
            self.assertEqual(sw._load_json(p, {}), {"a": 2})

    def test_ready_docs_db_only_in_db_mode(self):
        p = os.path.join(self.d, "steward", "quota.json")
        with mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "db"}):
            sd.write_json("steward/quota", p, {"q": 1}); self.assertTrue(os.path.exists(p))   # dosya AYNA
            open(p, "w").write('{"hand": 1}'); self.assertEqual(sd.read_json("steward/quota", p), {"q": 1})   # okuyucu DB

    def test_mocked_writer_never_touches_db_or_file(self):
        """2026-11-03 kazası: modülün atomic_write_json'u taklit eden test, gerçek settings.json/DB'yi ezdi."""
        from claudeops import settings
        calls = []
        real = os.path.join(self.d, "settings.json")
        with mock.patch.object(settings, "SETTINGS_JSON", real), mock.patch.object(settings, "atomic_write_json", lambda path, data, **kw: calls.append(data)), \
             mock.patch.object(settings, "load_settings", lambda: dict(settings.DEFAULT_SETTINGS)):
            settings.save_settings({"tunnel_watch": "off"})
        self.assertEqual(len(calls), 1); self.assertFalse(os.path.exists(real)); self.assertEqual(self.st.list_docs(), [])

    def test_instances_shadow(self):
        with mock.patch.object(ins, "INSTANCES_JSON", os.path.join(self.d, "instances.json")), \
             mock.patch.object(ins, "_LOCK_PATH", os.path.join(self.d, "instances.json.lock")):
            ins.record_instance("a", blueprint=None, cwd="/x", cli="claude", model="m", origin="t")
            self.assertIn("a", self.st.get_doc("instances")["instances"])


if __name__ == "__main__":
    unittest.main()

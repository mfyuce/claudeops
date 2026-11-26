"""db kipinde oturum kaydı DB satır sürümüne bağlı önbelleklenir: değişmeyen belge yeniden ayrıştırılmaz, değişen hemen
görülür (TBD#374 S4 korunur)."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import instances, statedocs as sd, store as S  # noqa: E402


class DbVersionCache(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp(prefix="cops-inst-")
        self.addCleanup(shutil.rmtree, d, True)
        self.d = d
        self.path = os.path.join(d, "instances.json")
        self.st = S.Store(os.path.join(d, "t.db"))
        self.addCleanup(self.st.close)
        for p in (mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "db",
                                               "CLAUDEOPS_DIAG_LOG": os.path.join(d, "diag.log")}),
                  mock.patch.object(S, "default_store", lambda: self.st),
                  mock.patch("claudeops.paths.CLAUDEOPS_DIR", d),
                  mock.patch.object(instances, "INSTANCES_JSON", self.path),
                  mock.patch.object(instances, "_cache_key", None),
                  mock.patch.object(instances, "_cache", {}),
                  mock.patch.object(instances, "_db_cache", None, create=True),
                  mock.patch.object(sd, "_DIRTY", set())):
            p.start()
            self.addCleanup(p.stop)
        self.reads = 0
        real = instances.read_strict

        def counting():
            self.reads += 1
            return real()
        p = mock.patch.object(instances, "read_strict", counting)
        p.start()
        self.addCleanup(p.stop)

    def put(self, *names):
        self.st.set_doc("instances", {"version": 1, "instances": {n: {} for n in names}})

    def names(self):
        return set(instances.load_instances())

    def test_unchanged_doc_parsed_once_and_change_seen(self):
        self.put("a")
        for _ in range(5):
            self.assertEqual(self.names(), {"a"})
        self.assertEqual(self.reads, 1)
        self.put("a", "b")                      # ayna dosyaya dokunmadan başka yazar
        self.assertEqual(self.names(), {"a", "b"})
        self.assertEqual(self.reads, 2)

    def test_returned_dict_is_a_copy(self):
        self.put("a")
        instances.load_instances().clear()
        self.assertEqual(self.names(), {"a"})

    def test_delete_and_recreate_with_same_version_seen(self):
        self.put("a")
        self.assertEqual(self.names(), {"a"})
        self.st.delete_doc("instances")
        self.put("z")                           # sürüm yeniden 1
        self.assertEqual(self.names(), {"z"})

    def test_dirty_mirror_not_cached(self):
        self.put("a")
        self.assertEqual(self.names(), {"a"})
        with open(self.path, "w", encoding="utf-8") as f:       # DB yazımı başarısız: dosya daha yeni
            f.write('{"version": 1, "instances": {"y": {}}}')
        sd._DIRTY.add("instances")
        self.assertEqual(self.names(), {"y"})

    def test_db_read_failure_fallback_not_cached(self):
        self.put("a")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"version": 1, "instances": {"eski": {}}}')
        with mock.patch.object(self.st, "get_doc", side_effect=RuntimeError("db")):
            self.assertEqual(self.names(), {"eski"})
        self.assertEqual(self.names(), {"a"})


if __name__ == "__main__":
    unittest.main()

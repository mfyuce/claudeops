"""agy_sids DB-doğruluk kaynağı (SQL göçü Adım C): kilitli oku-değiştir-yaz (eşzamanlı yazım kayıp vermez), DB kipinde okuma."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import statedocs as sd, store as S  # noqa: E402
from claudeops.providers import agy_provider as ap  # noqa: E402


class AgySidsStoreTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cops-agy-")
        self.p = os.path.join(self.d, "agy_sids.json")
        self.st = S.Store(os.path.join(self.d, "t.db"))
        self.ps = [mock.patch.object(S, "default_store", lambda: self.st), mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.d),
                   mock.patch.object(ap, "AGY_SIDS_JSON", self.p),
                   mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "db", "CLAUDEOPS_DIAG_LOG": os.path.join(self.d, "diag.log")})]
        [p.start() for p in self.ps]
        sd._SYNCED.clear()
        sd._DIRTY.clear()

    def tearDown(self):
        [p.stop() for p in self.ps]
        self.st.close()

    def test_db_ready(self):
        self.assertTrue(sd.db_ready("agy_sids"))

    def test_remember_writes_db_and_mirror(self):
        ap._remember_agy_sid("a", "sid-1")
        self.assertEqual(self.st.get_doc("agy_sids"), {"a": "sid-1"})
        self.assertTrue(os.path.exists(self.p))
        self.assertEqual(ap._load_agy_sids(), {"a": "sid-1"})
        os.remove(self.p)
        self.assertEqual(ap._load_agy_sids(), {"a": "sid-1"})        # db kipinde dosyaya bakılmaz

    def test_unchanged_value_does_not_rewrite(self):
        ap._remember_agy_sid("a", "sid-1")
        v = self.st.doc_version("agy_sids")
        ap._remember_agy_sid("a", "sid-1")
        self.assertEqual(self.st.doc_version("agy_sids"), v)

    def test_concurrent_remembers_lose_nothing(self):
        errs = []

        def work(i):
            try:
                for j in range(8):
                    ap._remember_agy_sid(f"s{i}_{j}", f"id{i}_{j}")
            except Exception as e:      # noqa: BLE001
                errs.append(e)
        ts = [threading.Thread(target=work, args=(i,)) for i in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        self.assertEqual(len(ap._load_agy_sids()), 48)


if __name__ == "__main__":
    unittest.main()

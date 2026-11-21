"""`cops db migrate-to-pg`: kuru koşu, doğrulama, dolu hedef reddi, kimlik dizisi, notes (enterprise varsa). Gerçek PG gerekir
(CLAUDEOPS_TEST_PG_URL; scripts/test-pg.sh), yoksa atlanır. Saf kısımlar (rapor, CLI sözleşmesi) PG'siz test edilir."""
import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import dbapi, dbcopy  # noqa: E402
from claudeops import store as S  # noqa: E402

PG = os.environ.get("CLAUDEOPS_TEST_PG_URL", "")


class Pure(unittest.TestCase):
    def test_requires_sqlite_to_pg(self):
        c = dbapi.connect("", ":memory:")
        with self.assertRaises(dbcopy.MigrateError):
            dbcopy.migrate_tables(c, c, [], False)
        with self.assertRaises(dbcopy.MigrateError):
            dbcopy.migrate_store("/x.db", "", False)

    def test_digest_is_order_and_value_sensitive(self):
        c = dbapi.connect("", ":memory:")
        c.execute("CREATE TABLE t(a INTEGER, b REAL)")
        c.execute("INSERT INTO t VALUES(1, 2.5)")
        d1 = dbcopy.table_digest(c, "t", "a", ["a", "b"])
        c.execute("UPDATE t SET b=2.6")
        self.assertNotEqual(d1, dbcopy.table_digest(c, "t", "a", ["a", "b"]))
        self.assertEqual(d1["count"], 1)


@unittest.skipUnless(PG, "CLAUDEOPS_TEST_PG_URL yok: Postgres testleri atlandı")
class RealPg(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.schema = "m_" + uuid.uuid4().hex[:12]
        self.adm = psycopg2.connect(PG)
        self.adm.autocommit = True
        self.adm.cursor().execute(f"CREATE SCHEMA {self.schema}")
        sep = "&" if "?" in PG else "?"
        self.url = f"{PG}{sep}options=-csearch_path%3D{self.schema}"
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "c.db")
        st = S.Store(self.path, "")
        st.set_doc("a", {"k": "değer ç"})
        st.set_doc("b", [1, 2, 3])
        for i in range(5):
            st.append_log("s", {"i": i})
        st.replace_tsv("roster.tsv", "ad\tx\n#kapali\ty\n")
        st.close()

    def tearDown(self):
        self.adm.cursor().execute(f"DROP SCHEMA {self.schema} CASCADE")
        self.adm.close()

    def test_dry_apply_verify_and_identity(self):
        rep = dbcopy.migrate_store(self.path, self.url, apply=False)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["tables"]["docs"]["source"]["count"], 2)
        self.assertEqual(rep["tables"]["docs"]["target_rows_before"], 0)
        rep = dbcopy.migrate_store(self.path, self.url, apply=True)
        self.assertTrue(rep.get("verified"), rep)
        self.assertEqual(rep["tables"]["log"]["target"], rep["tables"]["log"]["source"])
        dst = S.Store("", self.url)
        self.assertEqual(dst.get_doc("a"), {"k": "değer ç"})
        self.assertEqual(len(dst.read_log("s")), 5)
        self.assertEqual(dst.tsv_text("roster.tsv"), "ad\tx\n#kapali\ty\n")
        nxt = dst.append_log("s", {"i": 99})                          # kimlik dizisi MAX+1'den sürer
        self.assertEqual(nxt, 6)
        dst.close()

    def test_filled_target_refused_and_nothing_written(self):
        dbcopy.migrate_store(self.path, self.url, apply=True)
        rep = dbcopy.migrate_store(self.path, self.url, apply=True)
        self.assertFalse(rep["ok"])
        self.assertIn("hedefte dolu tablo", rep["error"])
        dst = S.Store("", self.url)
        self.assertEqual(len(dst.read_log("s")), 5)                    # çift kayıt yok
        dst.close()


if __name__ == "__main__":
    unittest.main()

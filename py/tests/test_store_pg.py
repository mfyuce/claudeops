"""store.py testleri Postgres arka ucunda (TODO Postgres hazırlığı madde 3). `CLAUDEOPS_TEST_PG_URL` yoksa TÜMÜ atlanır;
`scripts/test-pg.sh` geçici kapsayıcıyla koşturur. Her test KENDİ şemasında çalışır (search_path), bitince şema silinir."""
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import store as S  # noqa: E402
import test_store as TS  # noqa: E402
import test_store_edge as TE  # noqa: E402

PG = os.environ.get("CLAUDEOPS_TEST_PG_URL", "")
SQLITE_ONLY = ("test_file_mode_0600", "test_newer_db_refused", "test_processes_update_doc_no_lost_updates",
               "test_backup_leaves_no_tmp_and_unique_names", "test_backup_failure_cleans_tmp", "test_backup_consistent_and_private",
               "test_split_respects_quotes")


class PgSchema:
    """Test başına yalıtılmış şema + o şemaya bakan URL."""
    def pg_setup(self):
        import psycopg2
        self.schema = "t_" + uuid.uuid4().hex[:12]
        self._admin = psycopg2.connect(PG)
        self._admin.autocommit = True
        self._admin.cursor().execute(f"CREATE SCHEMA {self.schema}")
        sep = "&" if "?" in PG else "?"
        self.url = f"{PG}{sep}options=-csearch_path%3D{self.schema}"

    def pg_teardown(self):
        self._admin.cursor().execute(f"DROP SCHEMA {self.schema} CASCADE")
        self._admin.close()


def _skip_sqlite_only(cls):
    for n in SQLITE_ONLY:
        if hasattr(cls, n):
            setattr(cls, n, unittest.skip("SQLite'a özgü (dosya/yedek/user_version)")(lambda self: None))
    return cls


@unittest.skipUnless(PG, "CLAUDEOPS_TEST_PG_URL yok: Postgres testleri atlandı (scripts/test-pg.sh)")
@_skip_sqlite_only
class PgStoreTests(PgSchema, TS.StoreTests):
    def setUp(self):
        self.pg_setup()
        self.p = ""
        self.s = S.Store("", self.url)

    def tearDown(self):
        self.s.close()
        self.pg_teardown()

    def test_schema_version_and_idempotent_reopen(self):
        self.assertEqual(self.s.schema_version(), len(S.MIGRATIONS))
        self.s.set_doc("a", {"x": 1})
        s2 = S.Store("", self.url)          # ikinci açılış: göç tekrarlanmaz, veri korunur
        self.assertEqual(s2.get_doc("a"), {"x": 1})
        self.assertEqual(s2.schema_version(), len(S.MIGRATIONS))
        s2.close()

    def test_backend_is_postgres(self):
        self.assertEqual(self.s.backend, "postgres")
        self.assertEqual(self.s.schema_version(), len(S.MIGRATIONS))
        with self.assertRaises(S.StoreError):
            self.s.backup("/tmp/x.db")


@unittest.skipUnless(PG, "CLAUDEOPS_TEST_PG_URL yok: Postgres testleri atlandı")
@_skip_sqlite_only
class PgEdge(PgSchema, TE.Edge):
    def setUp(self):
        self.pg_setup()
        self.s = S.Store("", self.url)

    def tearDown(self):
        self.s.close()
        self.pg_teardown()


if __name__ == "__main__":
    unittest.main()

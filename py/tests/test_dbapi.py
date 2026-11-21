"""İnce DB-API katmanı (Postgres hazırlığı): çeviri, göç metni uyumu, eski user_version DB'si, PG yolunun gönderdiği SQL (sahte psycopg2).
Gerçek Postgres testleri yalnız CLAUDEOPS_TEST_PG_URL verilirse koşar (bu makinede PG sunucusu yok)."""
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import dbapi  # noqa: E402
from claudeops import store as S  # noqa: E402


class Translate(unittest.TestCase):
    def test_placeholders(self):
        self.assertEqual(dbapi.translate("SELECT 1 FROM t WHERE a=? AND b=?", dbapi.POSTGRES), "SELECT 1 FROM t WHERE a=%s AND b=%s")
        self.assertEqual(dbapi.translate("SELECT 1 WHERE a=?", dbapi.SQLITE), "SELECT 1 WHERE a=?")

    def test_string_literals_and_percent(self):
        q = dbapi.translate("SELECT name FROM docs WHERE name LIKE ? ESCAPE '\\' AND x='a?b' AND y='it''s ?'", dbapi.POSTGRES)
        self.assertEqual(q, "SELECT name FROM docs WHERE name LIKE %s ESCAPE '\\' AND x='a?b' AND y='it''s ?'")
        self.assertEqual(dbapi.translate("SELECT 100 % 7, 'a%'", dbapi.POSTGRES), "SELECT 100 %% 7, 'a%%'")

    def test_backend_of(self):
        self.assertEqual(dbapi.backend_of(""), dbapi.SQLITE)
        self.assertEqual(dbapi.backend_of("sqlite:///x.db"), dbapi.SQLITE)
        self.assertEqual(dbapi.backend_of("postgresql://u@h/d"), dbapi.POSTGRES)
        self.assertEqual(dbapi.backend_of("postgres://u@h/d"), dbapi.POSTGRES)
        with self.assertRaises(dbapi.DbError):
            dbapi.backend_of("mysql://x")
        self.assertEqual(dbapi.sqlite_path("sqlite:///tmp/a.db", "d"), "/tmp/a.db")
        self.assertEqual(dbapi.sqlite_path("", "d"), "d")


class Ddl(unittest.TestCase):
    def test_sqlite_ddl_identical_to_legacy(self):
        legacy_v1 = "id     INTEGER PRIMARY KEY AUTOINCREMENT,"
        self.assertIn(legacy_v1, dbapi.ddl(S.MIGRATIONS[0], dbapi.SQLITE))
        self.assertIn("ts     REAL NOT NULL", dbapi.ddl(S.MIGRATIONS[0], dbapi.SQLITE))
        self.assertNotIn("{", dbapi.ddl(S.MIGRATIONS[0], dbapi.SQLITE).replace("{REAL}", ""))

    def test_pg_ddl(self):
        t = dbapi.ddl(S.MIGRATIONS[0], dbapi.POSTGRES)
        self.assertIn("BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY", t)
        self.assertIn("DOUBLE PRECISION", t)
        self.assertNotIn("AUTOINCREMENT", t)
        self.assertNotRegex(t, r"\bREAL\b")

    def test_split_pg_dollar_quote(self):
        sql = "CREATE TABLE a(x int); CREATE FUNCTION f() RETURNS trigger AS $$ BEGIN RETURN NEW; END; $$ LANGUAGE plpgsql; INSERT INTO a VALUES ('x;y')"
        got = list(dbapi.split_statements(sql, dbapi.POSTGRES))
        self.assertEqual(len(got), 3)
        self.assertIn("RETURN NEW; END;", got[1])
        self.assertIn("'x;y'", got[2])


class LegacyUserVersion(unittest.TestCase):
    def test_old_db_without_schema_version_table(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "old.db")
            c = sqlite3.connect(p)
            for m in S.MIGRATIONS:
                for stmt in dbapi.split_statements(dbapi.ddl(m, dbapi.SQLITE), dbapi.SQLITE):
                    c.execute(stmt)
            c.execute(f"PRAGMA user_version={len(S.MIGRATIONS)}")
            c.execute("INSERT INTO docs(name,body,version,updated) VALUES('a','{\"k\":1}',1,1.0)")
            c.commit()
            c.close()
            st = S.Store(p, "")
            self.assertEqual(st.get_doc("a"), {"k": 1})                      # veri korunur
            self.assertEqual(st.schema_version(), len(S.MIGRATIONS))
            c = sqlite3.connect(p)
            self.assertEqual(c.execute("SELECT version FROM schema_version WHERE id=1").fetchone()[0], len(S.MIGRATIONS))
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], len(S.MIGRATIONS))
            c.close()
            st.close()

    def test_newer_user_version_still_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "n.db")
            S.Store(p, "").close()
            c = sqlite3.connect(p)
            c.execute(f"PRAGMA user_version={len(S.MIGRATIONS) + 3}")
            c.close()
            with self.assertRaises(S.StoreError):
                S.Store(p, "")


class FakePsycopg(unittest.TestCase):
    """PG yolunun gönderdiği SQL'i sahte psycopg2 ile yakalar (sunucu YOK; çeviri/RETURNING/kilit/BEGIN doğrulaması)."""

    def make(self):
        calls = []

        class Cur:
            rowcount = 1
            def __init__(self): self.rows = [(7,)]
            def execute(self, q, p=()): calls.append((q, tuple(p)))
            def executemany(self, q, rows): calls.append((q, "many", len(rows)))
            def fetchone(self): return self.rows[0]
            def fetchall(self): return self.rows

        class Raw:
            autocommit = False
            def cursor(self): return Cur()
            def close(self): pass

        fake = types.SimpleNamespace(connect=lambda url: Raw())
        return calls, fake

    def test_pg_statements(self):
        calls, fake = self.make()
        with mock.patch.dict(sys.modules, {"psycopg2": fake}):
            c = dbapi.connect("postgresql://u@h/d")
            self.assertTrue(c.raw.autocommit)
            c.begin_write()
            c.xact_lock("doc-a")
            c.execute("SELECT body FROM docs WHERE name=?" + c.for_update, ("a",))
            new_id = c.insert("INSERT INTO log(stream, ts, body) VALUES(?,?,?)", ("s", 1.0, "{}"))
            c.executemany("INSERT INTO tsv_rows(file) VALUES(?)", [("a",), ("b",)])
            c.commit()
        qs = [q for q, *_ in calls]
        self.assertEqual(qs[0], "BEGIN")
        self.assertIn("pg_advisory_xact_lock(hashtext(%s))", qs[1])
        self.assertEqual(qs[2], "SELECT body FROM docs WHERE name=%s FOR UPDATE")
        self.assertEqual(qs[3], "INSERT INTO log(stream, ts, body) VALUES(%s,%s,%s) RETURNING id")
        self.assertEqual(new_id, 7)
        self.assertEqual(qs[5], "COMMIT")

    def test_pg_migrate_uses_version_table_and_lock(self):
        calls, fake = self.make()
        with mock.patch.dict(sys.modules, {"psycopg2": fake}):
            c = dbapi.connect("postgresql://u@h/d")
            # schema_version tablosu yok: information_schema sorgusu 1 satır döndürmesin
            orig = c.execute

            def ex(sql, params=()):
                cur = orig(sql, params)
                if "information_schema" in sql:
                    cur.rows = [None]
                    cur.fetchone = lambda: None
                return cur
            c.execute = ex
            dbapi.migrate(c, ["CREATE TABLE a(x {REAL})"])
        qs = [q for q, *_ in calls]
        self.assertIn("pg_advisory_xact_lock(%s)", " ".join(qs))
        self.assertIn("CREATE TABLE a(x DOUBLE PRECISION)", qs)
        self.assertTrue(any("INSERT INTO schema_version" in q for q in qs))
        self.assertFalse(any("PRAGMA" in q for q in qs))

    def test_missing_psycopg2(self):
        with mock.patch.dict(sys.modules, {"psycopg2": None}):
            with self.assertRaises(dbapi.DbError):
                dbapi.connect("postgresql://u@h/d")


class MigrateEntries(unittest.TestCase):
    def test_per_backend_entry_and_own_version_table(self):
        with tempfile.TemporaryDirectory() as d:
            c = dbapi.connect("", os.path.join(d, "m.db"), named_rows=True)
            migs = ["CREATE TABLE a(id {PK_AUTO}, ts {REAL}, h TEXT)",
                    {"sqlite": ["CREATE TABLE b(x INTEGER)", "INSERT INTO b VALUES(1)"], "postgres": ["SELECT 1"]}]
            self.assertEqual(dbapi.migrate(c, migs, table="comp_version"), 2)
            self.assertEqual(dbapi.schema_version(c, "comp_version"), 2)
            self.assertEqual(c.execute("SELECT x FROM b").fetchone()["x"], 1)           # adlı satır
            self.assertEqual(dict(c.execute("SELECT x FROM b").fetchone()), {"x": 1})
            self.assertEqual(dbapi.schema_version(c), 2)                                 # SQLite: user_version de güncel
            self.assertEqual(dbapi.migrate(c, migs, table="comp_version"), 2)           # tekrar: değişiklik yok
            c.close()

    def test_randhex_token(self):
        self.assertIn("randomblob", dbapi.ddl("{RANDHEX}", dbapi.SQLITE))
        self.assertIn("md5(random()", dbapi.ddl("{RANDHEX}", dbapi.POSTGRES))


class SqliteStoreStillWorks(unittest.TestCase):
    def test_store_roundtrip_with_layer(self):
        with tempfile.TemporaryDirectory() as d:
            st = S.Store(os.path.join(d, "s.db"), "")
            self.assertEqual(st.backend, dbapi.SQLITE)
            st.set_doc("x", {"a": 1})
            self.assertEqual(st.update_doc("x", lambda v: dict(v, b=2)), {"a": 1, "b": 2})
            i = st.append_log("s", {"n": 1})
            self.assertEqual(st.read_log("s")[0][0], i)
            st.close()


@unittest.skipUnless(os.environ.get("CLAUDEOPS_TEST_PG_URL"), "CLAUDEOPS_TEST_PG_URL yok: gerçek Postgres testi atlandı")
class RealPostgres(unittest.TestCase):
    def test_store_on_pg(self):
        url = os.environ["CLAUDEOPS_TEST_PG_URL"]
        st = S.Store("", url)
        self.assertEqual(st.backend, dbapi.POSTGRES)
        st.set_doc("t_pg", {"a": 1})
        self.assertEqual(st.update_doc("t_pg", lambda v: dict(v, b=2)), {"a": 1, "b": 2})
        i = st.append_log("t_pg", {"n": 1})
        self.assertEqual(st.read_log("t_pg", after_id=i - 1)[0][0], i)
        self.assertEqual(st.schema_version(), len(S.MIGRATIONS))
        st.delete_doc("t_pg")
        st.trim_log("t_pg", 0)


if __name__ == "__main__":
    unittest.main()

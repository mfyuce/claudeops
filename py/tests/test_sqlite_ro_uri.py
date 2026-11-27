"""Sohbet dökümü ve ucli ölçüm okuyucusu: yoldaki `#`, `?`, `%` SQLite `file:` URI'sinde kaçışlanır. Kaçışsızken başka
dosya açılıyor, `mode=ro` düşüyor ve boş dosya yaratılıyordu."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import chat_dump, ucli_metrics  # noqa: E402

NAMES = ["duz", "a#b", "a?b", "a%41b", "bo şluk", "x?mode=rwc&y"]


class ReadOnlyUri(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def db(self, name):
        d = os.path.join(self.root, name)
        os.makedirs(d)
        p = os.path.join(d, "x.db")
        c = sqlite3.connect(p)
        with c:
            c.execute("CREATE TABLE t(v TEXT)")
            c.execute("INSERT INTO t VALUES (?)", (name,))
        c.close()
        return p

    def tree(self):
        return sorted(os.path.join(r, n) for r, ds, fs in os.walk(self.root) for n in ds + fs)

    def check(self, opener, name, path):
        before = self.tree()
        c = opener(path)
        try:
            self.assertEqual(c.execute("SELECT v FROM t").fetchall(), [(name,)])
            with self.assertRaises(sqlite3.OperationalError):
                c.execute("INSERT INTO t VALUES ('yaz')")
        finally:
            c.close()
        self.assertEqual(self.tree(), before)

    def test_openers_read_the_exact_file_read_only(self):
        for opener in (chat_dump._ro, ucli_metrics._read_conn):
            for name in NAMES:
                with self.subTest(opener=opener.__name__, name=name):
                    path = os.path.join(self.root, name, "x.db")
                    if not os.path.exists(path):
                        self.db(name)
                    self.check(opener, name, path)

    def test_double_slash_path_is_not_a_host(self):
        path = "/" + self.db("cift")
        for opener in (chat_dump._ro, ucli_metrics._read_conn):
            self.check(opener, "cift", path)


if __name__ == "__main__":
    unittest.main()

"""Store: boş TSV 'yok' sayılmaz; migrasyon bölücü tırnak içi ';'yi bölmez (review cops 2 Kas)."""
import os
import tempfile
import unittest

from claudeops import store


class Edge(unittest.TestCase):
    def setUp(self):
        self.s = store.Store(os.path.join(tempfile.mkdtemp(), "t.db"))

    def test_empty_tsv_is_empty_string_not_none(self):
        self.assertIsNone(self.s.tsv_text("a.tsv"))
        self.assertEqual(self.s.replace_tsv("a.tsv", ""), 0)
        self.assertEqual(self.s.tsv_text("a.tsv"), "")
        self.assertEqual(self.s.tsv_rows("a.tsv"), [])
        self.s.replace_tsv("a.tsv", "x\ty\n")
        self.assertEqual(self.s.tsv_text("a.tsv"), "x\ty\n")
        self.s.replace_tsv("a.tsv", "")
        self.assertEqual(self.s.tsv_text("a.tsv"), "")

    def test_split_respects_quotes(self):
        got = list(store._split("INSERT INTO t VALUES ('a;b'); CREATE TABLE u(x); "))
        self.assertEqual(got, ["INSERT INTO t VALUES ('a;b')", "CREATE TABLE u(x)"])
        self.assertEqual(list(store._split("A; B")), ["A", "B"])


if __name__ == "__main__":
    unittest.main()

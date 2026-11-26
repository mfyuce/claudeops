"""agy/copilot SQLite sohbet okuyucuları (rs/prov G2): yol kaçışlanır, tek bozuk hücre sağlam satırları düşürmez.

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_sqlite_readers.py
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.providers import agy_provider, copilot_provider  # noqa: E402
from test_agy_compaction_view import _ld  # noqa: E402

U = lambda t: _ld(19, _ld(2, t))
A = lambda t: _ld(20, _ld(1, t))
PAIR = [{"role": "user", "text": "s"}, {"role": "assistant", "text": "c"}]


def make_db(path, script, rows=(), insert=""):
    db = sqlite3.connect(path)
    db.execute(script)
    if rows:
        db.executemany(insert, rows)
    db.commit()
    db.close()


def steps(path, rows):
    make_db(path, "CREATE TABLE steps (idx INTEGER, step_type INTEGER, step_payload BLOB)", rows,
            "INSERT INTO steps VALUES (?,?,?)")


class UriTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def test_agy_special_characters_in_the_path(self):
        for name in ("a#b", "a?b", "a%41b", "a b ğ"):
            with self.subTest(name=name):
                d = os.path.join(self.root, "d-" + name)
                os.mkdir(d)
                steps(os.path.join(d, name + ".db"), [(0, 14, U(b"s")), (1, 15, A(b"c"))])
                before = sorted(os.listdir(self.root)), sorted(os.listdir(d))
                with mock.patch.object(agy_provider, "CONVERSATIONS_DIR", d):
                    p = agy_provider.AgyProvider()
                    self.assertEqual(p.full_history("x", name), PAIR)
                    self.assertEqual(p.last_exchange("x", name), {"user": "s", "assistant": "c"})
                # kesilmiş yolla boş dosya yaratılmaz
                self.assertEqual((sorted(os.listdir(self.root)), sorted(os.listdir(d))), before)

    def test_copilot_special_characters_in_the_path(self):
        for name in ("a#b", "a?b"):
            with self.subTest(name=name):
                d = os.path.join(self.root, name)
                os.mkdir(d)
                path = os.path.join(d, "store.db")
                make_db(path, "CREATE TABLE turns (session_id TEXT, turn_index INT, user_message, assistant_response)",
                        [("s1", 0, "s", "c")], "INSERT INTO turns VALUES (?,?,?,?)")
                before = sorted(os.listdir(self.root))
                with mock.patch.object(copilot_provider, "SESSION_STORE_DB", path):
                    self.assertEqual(copilot_provider.CopilotProvider().full_history("x", "s1"), PAIR)
                self.assertEqual(sorted(os.listdir(self.root)), before)

    def test_read_only_is_kept(self):
        path = os.path.join(self.root, "a#b.db")
        with mock.patch.object(copilot_provider, "SESSION_STORE_DB", path):
            with self.assertRaises(sqlite3.OperationalError):
                copilot_provider._connect_ro()                   # yok olan dosya yaratılmaz
        self.assertEqual(os.listdir(self.root), [])


if __name__ == "__main__":
    unittest.main()

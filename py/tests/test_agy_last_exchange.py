"""agy `last_exchange` sondan tembel okur (uzak mode=last 13 sn yavaşlığı): sonuç eskisiyle aynı, bütün konuşmayı çekmez."""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.providers import agy_provider  # noqa: E402
from test_agy_compaction_view import _ld  # noqa: E402


def _db(d, rows):
    db = sqlite3.connect(os.path.join(d, "abc.db"))
    db.execute("CREATE TABLE steps (idx INTEGER, step_type INTEGER, step_payload BLOB)")
    db.executemany("INSERT INTO steps VALUES (?,?,?)", rows)
    db.commit()
    db.close()


U = lambda t: _ld(19, _ld(2, t))
A = lambda t: _ld(20, _ld(1, t))


class AgyLastExchange(unittest.TestCase):
    def _last(self, rows):
        with tempfile.TemporaryDirectory() as d:
            _db(d, rows)
            with mock.patch.object(agy_provider, "CONVERSATIONS_DIR", d):
                return agy_provider.AgyProvider().last_exchange("x", "abc")

    def test_last_pair_skips_empty_assistant_steps(self):
        r = self._last([(0, 14, U(b"ilk")), (1, 15, A(b"c1")), (2, 14, U(b"ikinci")), (3, 15, A(b"c2")), (4, 15, _ld(20, b""))])
        self.assertEqual(r, {"user": "ikinci", "assistant": "c2"})

    def test_empty_conversation_and_no_assistant(self):
        self.assertEqual(self._last([]), {"user": "", "assistant": ""})
        self.assertEqual(self._last([(0, 14, U(b"x"))]), {"user": "", "assistant": ""})

    def test_checkpoint_between_does_not_break_pairing(self):
        r = self._last([(0, 14, U(b"s")), (1, 23, b"x<summary>o</summary>"), (2, 15, A(b"c"))])
        self.assertEqual(r, {"user": "s", "assistant": "c"})

    def test_missing_db_is_empty(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(agy_provider, "CONVERSATIONS_DIR", d):
            self.assertEqual(agy_provider.AgyProvider().last_exchange("x", "nope"), {"user": "", "assistant": ""})


if __name__ == "__main__":
    unittest.main()

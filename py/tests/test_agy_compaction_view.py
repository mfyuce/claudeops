"""agy Sohbet geçmişi: type-23 `<summary>` kontrol noktası sınır işareti olur (TBD#89, yalnız görünüm)."""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.providers import agy_provider  # noqa: E402


def _ld(field_no, data):
    tag = (field_no << 3) | 2
    head = bytes([(tag & 0x7F) | 0x80, tag >> 7]) if tag > 127 else bytes([tag])
    return head + bytes([len(data)]) + data


class AgyCompactionViewTests(unittest.TestCase):
    def test_checkpoint_becomes_boundary_and_plain_type23_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            db = sqlite3.connect(os.path.join(d, "abc.db"))
            db.execute("CREATE TABLE steps (idx INTEGER, step_type INTEGER, step_payload BLOB)")
            rows = [
                (0, 14, _ld(19, _ld(2, b"soru"))),
                (1, 15, _ld(20, _ld(1, b"cevap"))),
                (2, 23, b"baska bir type-23 adimi"),
                (3, 23, b"x<summary>ozet</summary>"),
                (4, 14, _ld(19, _ld(2, b"yeni"))),
            ]
            db.executemany("INSERT INTO steps VALUES (?,?,?)", rows)
            db.commit()
            db.close()
            with mock.patch.object(agy_provider, "CONVERSATIONS_DIR", d):
                h = agy_provider.AgyProvider().full_history("x", "abc")
        self.assertEqual([m["role"] for m in h], ["user", "assistant", "boundary", "user"])
        self.assertEqual(h[0]["text"], "soru")


if __name__ == "__main__":
    unittest.main()

import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import files  # noqa: E402


class WriteUploadFsyncTest(unittest.TestCase):
    def test_fsync_before_replace_and_incomplete_leaves_target(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "a.bin")
            open(dest, "wb").write(b"eski")
            order = []
            real_fsync, real_replace = os.fsync, os.replace
            with mock.patch("os.fsync", side_effect=lambda fd: (order.append("fsync"), real_fsync(fd))[1]), \
                    mock.patch("os.replace", side_effect=lambda a, b: (order.append("replace"), real_replace(a, b))[1]):
                self.assertIsNone(files.write_upload(dest, io.BytesIO(b"yeni"), 4, 2))
            self.assertEqual(order, ["fsync", "replace"])
            self.assertEqual(open(dest, "rb").read(), b"yeni")
            self.assertEqual(files.write_upload(dest, io.BytesIO(b"x"), 4, 2), "incomplete")   # yarım gövde
            self.assertEqual(open(dest, "rb").read(), b"yeni")                                 # hedef bozulmadı
            self.assertEqual([n for n in os.listdir(d) if n != "a.bin"], [])                   # tmp temizlendi


if __name__ == "__main__":
    unittest.main()

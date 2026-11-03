"""atomic_json: os.replace sonrası dizin fsync (P3 #35) ve os.fdopen düşerse fd sızmaz (P3 #40)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import atomic_json as aj  # noqa: E402


class DirFsyncTest(unittest.TestCase):
    def test_directory_is_fsynced_after_replace(self):
        order = []
        real_replace, real_fsync = os.replace, os.fsync
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")

            def rep(a, b):
                order.append("replace")
                return real_replace(a, b)

            def fs(fd):
                order.append("fsync")
                return real_fsync(fd)

            with mock.patch.object(aj.os, "replace", rep), mock.patch.object(aj.os, "fsync", fs):
                aj.atomic_write_text(p, "x")
            self.assertEqual(order, ["fsync", "replace", "fsync"])      # dosya fsync, replace, dizin fsync


class FdopenLeakTest(unittest.TestCase):
    def test_fd_closed_when_fdopen_fails(self):
        closed = []
        real_close = os.close
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            with mock.patch.object(aj.os, "fdopen", side_effect=OSError("boom")), \
                    mock.patch.object(aj.os, "close", lambda fd: (closed.append(fd), real_close(fd))[1]):
                with self.assertRaises(OSError):
                    aj.atomic_write_text(p, "x")
            self.assertEqual(len(closed), 1)
            self.assertEqual(os.listdir(d), [])             # tmp de sızmaz


if __name__ == "__main__":
    unittest.main()

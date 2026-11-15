"""web._atomic_write_text: replace'ten ÖNCE dosya fsync'i, sonra dizin fsync'i (güç kesintisinde boş roster/models kalmasın)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


class AtomicWriteFsync(unittest.TestCase):
    def test_fsync_before_replace_and_dir_after(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "roster.tsv")
        open(path, "w").write("old\n")
        order = []
        real_fsync, real_replace = os.fsync, os.replace
        with mock.patch("claudeops.statedocs.shadow_tsv"), \
             mock.patch.object(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1]), \
             mock.patch.object(os, "replace", lambda a, b: (order.append("replace"), real_replace(a, b))[1]):
            web._atomic_write_text(path, "new\n")
        self.assertEqual(open(path).read(), "new\n")
        self.assertEqual(order, ["fsync", "replace", "fsync"])


if __name__ == "__main__":
    unittest.main()

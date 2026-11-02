"""atomic_json: mode=None mevcut hedefin iznini korur; açık mode umask'a rağmen uygulanır; tmp kalmaz."""
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.atomic_json import atomic_write_json, atomic_write_text  # noqa: E402


class AtomicModeTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.d, ignore_errors=True))

    def _mode(self, p):
        return stat.S_IMODE(os.stat(p).st_mode)

    def test_existing_mode_preserved_text(self):
        p = os.path.join(self.d, "a.txt")
        open(p, "w").write("x")
        os.chmod(p, 0o600)
        atomic_write_text(p, "yeni")
        self.assertEqual(self._mode(p), 0o600)
        self.assertEqual(open(p).read(), "yeni")

    def test_existing_mode_preserved_json(self):
        p = os.path.join(self.d, "a.json")
        open(p, "w").write("{}")
        os.chmod(p, 0o640)
        atomic_write_json(p, {"a": 1})
        self.assertEqual(self._mode(p), 0o640)

    def test_explicit_mode_beats_umask(self):
        p = os.path.join(self.d, "b.json")
        old = os.umask(0o077)
        try:
            atomic_write_json(p, {}, mode=0o664)
        finally:
            os.umask(old)
        self.assertEqual(self._mode(p), 0o664)

    def test_no_tmp_left(self):
        p = os.path.join(self.d, "c.txt")
        atomic_write_text(p, "x")
        self.assertEqual(os.listdir(self.d), ["c.txt"])


if __name__ == "__main__":
    unittest.main()

"""TBD#383 (4): oturum kaydı kilidi sembolik bağı izlemesin, hedefi boşaltmasın."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import atomic_json as aj  # noqa: E402
from claudeops import instances  # noqa: E402


class InstancesLockSymlink(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name
        self.lock = os.path.join(self.d, "instances.json.lock")
        p = mock.patch.object(instances, "_LOCK_PATH", self.lock)
        p.start()
        self.addCleanup(p.stop)

    def test_symlink_refused_target_untouched(self):
        victim = os.path.join(self.d, "kurban")
        with open(victim, "w") as f:
            f.write("onemli")
        os.symlink(victim, self.lock)
        ran = []
        with self.assertRaises(aj.LockError):
            with instances._locked():
                ran.append(1)
        self.assertEqual(ran, [])
        with open(victim) as f:
            self.assertEqual(f.read(), "onemli")

    def test_content_kept_and_foreign_owner_refused(self):
        with open(self.lock, "w") as f:
            f.write("iz")
        with instances._locked():
            pass
        with open(self.lock) as f:
            self.assertEqual(f.read(), "iz")
        with mock.patch.object(aj.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(aj.LockError):
                with instances._locked():
                    pass


if __name__ == "__main__":
    unittest.main()

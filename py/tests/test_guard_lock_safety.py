"""guard.lock /tmp'de paylaşımlı: symlink hedefi truncate edilmez, sahibi biz olmayan dizin/dosya reddedilir."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import guard  # noqa: E402


class GuardLockSafetyTest(unittest.TestCase):
    def setUp(self):
        self.d = os.path.realpath(tempfile.mkdtemp())
        self.lock = os.path.join(self.d, "claudeops", "guard.lock")
        p = mock.patch.object(guard, "GUARD_LOCK", self.lock)
        p.start()
        self.addCleanup(p.stop)

    def test_normal_lock_and_reentry_timeout(self):
        with guard.guard_lock(timeout=1):
            self.assertEqual(os.stat(self.lock).st_mode & 0o777, 0o600)
            with self.assertRaises(TimeoutError):
                with guard.guard_lock(timeout=0.6):
                    pass

    def test_symlink_lock_not_truncated(self):
        os.makedirs(os.path.dirname(self.lock))
        victim = os.path.join(self.d, "victim.txt")
        open(victim, "w").write("ONEMLI")
        os.symlink(victim, self.lock)
        with self.assertRaises(OSError):
            with guard.guard_lock(timeout=1):
                pass
        self.assertEqual(open(victim).read(), "ONEMLI")

    def test_symlinked_or_foreign_dir_refused(self):
        real = os.path.join(self.d, "real")
        os.makedirs(real)
        os.symlink(real, os.path.join(self.d, "claudeops"))
        with self.assertRaises(PermissionError):
            with guard.guard_lock(timeout=1):
                pass
        os.unlink(os.path.join(self.d, "claudeops"))
        os.makedirs(os.path.dirname(self.lock))
        with mock.patch.object(guard.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(PermissionError):
                with guard.guard_lock(timeout=1):
                    pass


if __name__ == "__main__":
    unittest.main()

"""TODO rs-prov "#397 ajanının gördüğü": `instances` kilidi reddedilince (bağlantı, yabancı dosya, zaman aşımı) yazım
yine yapılmaz (gövde koşmaz) ama `file_lock_refused` izi kalır (`atomic_json.file_lock` ile aynı olay). Yalnız geçici dizin."""
import fcntl
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import atomic_json, instances  # noqa: E402


class InstancesLockRefusalIsLogged(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.path = os.path.join(d.name, "instances.json")
        self.logs = []
        for p in (mock.patch.object(instances, "INSTANCES_JSON", self.path),
                  mock.patch.object(instances, "_LOCK_PATH", self.path + ".lock"),
                  mock.patch.object(instances, "diag_log", lambda ev, **k: self.logs.append((ev, k)))):
            p.start()
            self.addCleanup(p.stop)

    def refused(self):
        ran = []
        with self.assertRaises(atomic_json.LockError):
            with instances._locked():
                ran.append(1)
        self.assertEqual(ran, [])
        self.assertEqual(self.logs, [("file_lock_refused", {"path": self.path})])

    def test_symlinked_lock_file(self):
        os.symlink(os.path.join(os.path.dirname(self.path), "baska"), self.path + ".lock")
        self.refused()

    def test_lock_held_elsewhere(self):
        fd = os.open(self.path + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        with mock.patch.object(atomic_json, "LOCK_TIMEOUT_SECONDS", 0.05):
            self.refused()

    def test_success_logs_nothing(self):
        with instances._locked():
            pass
        self.assertEqual([e for e, _ in self.logs if e == "file_lock_refused"], [])


if __name__ == "__main__":
    unittest.main()

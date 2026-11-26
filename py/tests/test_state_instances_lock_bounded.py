"""TBD#374 (a) S6: oturum kaydı kilidi süresiz beklemez."""
import fcntl
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import atomic_json as aj  # noqa: E402
from claudeops import instances  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name

    def patch(self, obj, name, value):
        p = mock.patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)

    def hold(self, lock_path):
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)


class InstancesLockBounded(_Tmp):
    def test_s6_instances_lock_is_bounded(self):
        lock = os.path.join(self.d, "instances.json.lock")
        self.patch(instances, "_LOCK_PATH", lock)
        self.patch(instances, "INSTANCES_JSON", os.path.join(self.d, "instances.json"))
        self.patch(aj, "LOCK_TIMEOUT_SECONDS", 0.2)
        self.hold(lock)
        import threading
        box = []

        def work():
            try:
                instances.record_instance("a", blueprint=None, cwd="/c", cli="claude", model="m", origin="t")
            except BaseException as e:
                box.append(e)

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(5)
        self.assertFalse(t.is_alive(), "süresiz bekledi")
        self.assertIsInstance(box[0], aj.LockError)
        self.assertFalse(os.path.exists(instances.INSTANCES_JSON))


if __name__ == "__main__":
    unittest.main()

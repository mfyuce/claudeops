"""TBD#374 (a) S1/S5: kilit alınamazsa gövde çalışmaz."""
import fcntl
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import atomic_json as aj  # noqa: E402
from claudeops import diaglog  # noqa: E402


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


class FileLockFailsClosed(_Tmp):
    def _refused(self, path):
        ran, logged = [], []
        with mock.patch.object(diaglog, "diag_log", lambda event, **kw: logged.append((event, kw))):
            with self.assertRaises(aj.LockError):
                with aj.file_lock(path):
                    ran.append(1)
        self.assertEqual(ran, [])
        self.assertEqual(logged, [("file_lock_refused", {"path": path})])
        self.assertNotIn(path, aj._THREAD_LOCKS)

    def test_s1_timeout_raises(self):
        path = os.path.join(self.d, "x.json")
        self.hold(path + ".lock")
        self.patch(aj, "LOCK_TIMEOUT_SECONDS", 0.2)
        self._refused(path)

    def test_s5_symlink_lock_raises_and_target_untouched(self):
        path = os.path.join(self.d, "x.json")
        os.symlink(os.path.join(self.d, "victim"), path + ".lock")
        self._refused(path)
        self.assertFalse(os.path.exists(os.path.join(self.d, "victim")))

    def test_s5_foreign_owner_raises(self):
        self.patch(aj.os, "getuid", lambda uid=os.getuid(): uid + 1)
        self._refused(os.path.join(self.d, "x.json"))

    def test_unusable_directory_is_logged_too(self):
        blocker = os.path.join(self.d, "dosya")
        open(blocker, "w").close()
        self._refused(os.path.join(blocker, "x.json"))

    def test_refusal_reaches_the_real_diag_log_even_for_the_settings_file(self):
        log = os.path.join(self.d, "diag.log")
        path = os.path.join(self.d, "settings.json")
        os.symlink(os.path.join(self.d, "victim"), path + ".lock")
        with mock.patch.dict(os.environ, {"CLAUDEOPS_DIAG_LOG": log}):
            with self.assertRaises(aj.LockError):
                with aj.file_lock(path):
                    pass
        with open(log, encoding="utf-8") as f:
            self.assertEqual([(r["event"], r["path"]) for r in map(json.loads, f)], [("file_lock_refused", path)])

    def test_success_logs_nothing(self):
        logged = []
        with mock.patch.object(diaglog, "diag_log", lambda *a, **k: logged.append(a)):
            with aj.file_lock(os.path.join(self.d, "y.json")):
                pass
        self.assertEqual(logged, [])

    def test_error_inside_body_is_not_converted(self):
        with self.assertRaises(FileNotFoundError):
            with aj.file_lock(os.path.join(self.d, "x.json")):
                raise FileNotFoundError("gövde")


if __name__ == "__main__":
    unittest.main()

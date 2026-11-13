"""file_lock: süreçler-arası flock zaman aşımına uğrar (süresiz asılmaz), uyarıyla thread-kilidine düşer (review cliops 3 Kas)."""
import fcntl
import os
import tempfile
import time
import unittest
from unittest import mock

from claudeops import atomic_json as aj


class LockTimeout(unittest.TestCase):
    def test_times_out_instead_of_hanging(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "x.json")
        holder = os.open(path + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(holder, fcntl.LOCK_EX)
        try:
            with mock.patch.object(aj, "LOCK_TIMEOUT_SECONDS", 0.3):
                t0 = time.monotonic()
                with aj.file_lock(path):
                    pass
                self.assertLess(time.monotonic() - t0, 5)
        finally:
            os.close(holder)

    def test_normal_acquire(self):
        d = tempfile.mkdtemp()
        with aj.file_lock(os.path.join(d, "y.json")):
            pass


if __name__ == "__main__":
    unittest.main()

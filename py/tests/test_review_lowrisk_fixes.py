"""review cliops/uzops bulguları (18 Kas): kill_session AccessDenied, periodic config oku-değiştir-yaz kaybı."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

import psutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import kill, periodic as P  # noqa: E402


class KillSessionAccessDenied(unittest.TestCase):
    def test_send_signal_access_denied_is_already_dead(self):
        proc = mock.Mock()
        proc.send_signal.side_effect = psutil.AccessDenied(pid=1)
        with mock.patch.object(kill.psutil, "Process", return_value=proc):
            self.assertEqual(kill.kill_session(1, grace=0.1), "already_dead")
        proc.kill.assert_not_called()

    def test_create_time_access_denied_is_already_dead(self):
        proc = mock.Mock()
        proc.create_time.side_effect = psutil.AccessDenied(pid=1)
        with mock.patch.object(kill.psutil, "Process", return_value=proc):
            self.assertEqual(kill.kill_session(1, grace=0.1, create_time=5.0), "already_dead")
        proc.send_signal.assert_not_called()


class PeriodicConfigLock(unittest.TestCase):
    def test_concurrent_add_custom_loses_nothing(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(P, "CONFIG_JSON", os.path.join(d, "periodic.json")):
            errs = []

            def add(i):
                try:
                    P.add_custom(f"job{i:02d}", {"command": "true", "schedule": "0 1 * * *"})
                except Exception as e:      # noqa: BLE001
                    errs.append(repr(e))
            ts = [threading.Thread(target=add, args=(i,)) for i in range(12)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertEqual(errs, [])
            have = [k for k in P.load_config() if k.startswith("job")]
            self.assertEqual(len(have), 12)          # kilitsiz RMW'de bazıları kaybolurdu


if __name__ == "__main__":
    unittest.main()

"""GATE-TODO satır 25: port açılmazsa uzakgoz süreci sonlandırılır, durum temizlenir.

Çalıştırma:  python3 py/tests/test_remote_desktop_start_timeout.py -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import remote_desktop as rd  # noqa: E402


class StartTimeoutTest(unittest.TestCase):
    def test_timeout_terminates_process_and_clears_state(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 4242
        with tempfile.TemporaryDirectory() as d:
            fake_bin = Path(d) / "uzakgoz"
            fake_bin.write_text("")
            with mock.patch.object(rd, "uzakgoz_config", lambda: {"port": 0, "bin": str(fake_bin)}), \
                 mock.patch.object(rd, "_adopt_if_orphaned", lambda: None), \
                 mock.patch.object(rd, "_port_open", lambda p: False), \
                 mock.patch.object(rd, "PORT_WAIT_SECONDS", 0.2), \
                 mock.patch.object(rd.subprocess, "Popen", lambda *a, **k: proc):
                rd._proc = None
                r = rd.start(port=45999)
        self.assertFalse(r["ok"])
        proc.terminate.assert_called_once()
        self.assertIsNone(rd._proc)
        self.assertIsNone(rd._port)


if __name__ == "__main__":
    unittest.main()

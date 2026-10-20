"""`tmux_send_keys` zaman aşımı metin uzunluğuyla büyür (uzun beyin turu 5 sn'de kesilip Enter'sız kalıyordu). tmux'a DOKUNMAZ."""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import tmux_backend  # noqa: E402


class SendTimeoutTest(unittest.TestCase):
    def _timeouts(self, text):
        seen = []

        def fake_run(argv, capture_output=True, timeout=None):
            seen.append(timeout)
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch.object(tmux_backend.subprocess, "run", fake_run), \
                mock.patch.object(tmux_backend, "_exact", lambda n: n):
            self.assertTrue(tmux_backend.tmux_send_keys("x", text))
        return seen

    def test_short_text_keeps_base_timeout_long_text_gets_more(self):
        short = self._timeouts("merhaba")
        self.assertEqual(short[0], tmux_backend._TIMEOUT + 7 / 1500.0)
        long = self._timeouts("x" * 24000)
        self.assertEqual(long[0], 5.0 + 16.0)
        self.assertGreater(long[0], short[0])


if __name__ == "__main__":
    unittest.main()

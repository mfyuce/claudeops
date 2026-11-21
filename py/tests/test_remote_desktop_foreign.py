"""remote_desktop.start(): portu tutan, panel dışından başlatılmış AYNI ikili (pid/token dosyası yok) durdurulup panelce yeniden başlatılır;
başka ikili/başka süreç portu tutuyorsa eski hata kalır. Gerçek süreç taraması `sleep` ile (kendi kullanıcımız), sinyal/ağ sahte."""
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import remote_desktop as rd  # noqa: E402
from test_remote_desktop_token import _Base  # noqa: E402


class FindForeign(unittest.TestCase):
    def test_finds_same_exe_and_port_only(self):
        sleep = shutil.which("sleep")
        p = subprocess.Popen([sleep, "987"])
        try:
            self.assertEqual(rd._find_foreign_daemon(987, Path(sleep)), p.pid)
            self.assertIsNone(rd._find_foreign_daemon(988, Path(sleep)))          # başka port
            self.assertIsNone(rd._find_foreign_daemon(987, Path(shutil.which("true") or "/bin/true")))   # başka ikili
        finally:
            p.kill()
            p.wait()


class StartTakesOverForeign(_Base):
    def _run(self, foreign, port_open):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 4242
        with mock.patch.object(rd, "uzakgoz_config", return_value={"dir": "", "bin": "/bin/true", "port": 9123}), \
                mock.patch.object(rd, "_adopt_if_orphaned"), mock.patch.object(rd, "_port_open", side_effect=port_open), \
                mock.patch.object(rd, "_find_foreign_daemon", return_value=foreign), mock.patch.object(rd, "_kill_pid") as kill, \
                mock.patch.object(rd.subprocess, "Popen", return_value=proc) as popen:
            res = rd.start()
        return res, kill, popen

    def test_foreign_same_binary_is_killed_then_started(self):
        res, kill, popen = self._run(777, [True, False, True])
        kill.assert_called_once_with(777)
        self.assertTrue(res["ok"])
        self.assertTrue(popen.called)
        self.assertTrue(os.path.exists(self.pidfile) and os.path.exists(self.tokfile))      # panel artık sahipleniyor

    def test_unknown_holder_still_refused(self):
        res, kill, popen = self._run(None, [True, True])
        kill.assert_not_called()
        self.assertFalse(res["ok"])
        self.assertIn("başka bir süreç", res["error"])
        self.assertFalse(popen.called)


if __name__ == "__main__":
    unittest.main()

"""Açılışta ölen ucli oturumu: başlatma yanıtı pane'deki son `Error:` satırını taşır (yalnız "proc görünmedi" değil)."""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import tmux_backend  # noqa: E402
from claudeops.commands import web  # noqa: E402

PANE = ("user@host:/tmp/x$ ucli chat\n"
        "error: eski satır\n"
        "\x1b[31mError: --max-session-usd needs a price for this model\x1b[0m\n"
        "user@host:/tmp/x$ \n")


class StartErrorLineTests(unittest.TestCase):
    def _start(self, cli="ucli", stable=True, died=True, pane=PANE):
        info = {"state": "active", "cli": cli, "model": "m", "cwd": "/tmp/x", "permission_mode": "auto", "effort": "low"}
        with mock.patch.object(web, "_fleet_status", return_value={"p": info}), \
             mock.patch.object(web, "find_sessions", return_value=[]), \
             mock.patch.object(web, "spawn_session", return_value="new"), \
             mock.patch.object(web, "guard_lock", mock.MagicMock()), \
             mock.patch.object(web, "_wait_stable", return_value=stable), \
             mock.patch.object(web, "_died_within", return_value=died), \
             mock.patch.object(web.trust_dialog, "handle", return_value="none"), \
             mock.patch.object(web, "tmux_capture", return_value=pane) as cap, \
             mock.patch.object(web, "diag_log", lambda ev, **kw: None), \
             mock.patch.object(web.inst_mod, "mark_started"):
            return web._start("p"), cap

    def test_died_early_carries_last_error_line(self):
        out, _ = self._start()
        self.assertEqual(out["code"], "start_died_early")
        self.assertIn("needs a price for this model", out["error"])
        self.assertNotIn("eski satır", out["error"])
        self.assertNotIn("\x1b", out["error"])
        self.assertNotIn("user@host", out["error"])

    def test_no_proc_carries_last_error_line(self):
        out, _ = self._start(stable=False)
        self.assertEqual(out["code"], "start_no_proc")
        self.assertIn("needs a price", out["error"])

    def test_secret_is_masked(self):
        key = "sk-ant-api03-" + "A" * 40
        out, _ = self._start(pane=f"Error: bad key {key}\n")
        self.assertIn("bad key", out["error"])
        self.assertNotIn(key, out["error"])

    def test_pane_without_error_line_adds_nothing(self):
        plain, _ = self._start(pane=None)
        out, _ = self._start(pane="user@host:/tmp/x$ gizli komut çıktısı\n")
        self.assertEqual(out["error"], plain["error"])

    def test_capture_failure_never_breaks_start_answer(self):
        with mock.patch.object(web, "strip_ansi", side_effect=RuntimeError("x")):
            out, _ = self._start()
        self.assertEqual(out["code"], "start_died_early")

    def test_other_cli_pane_is_not_read(self):
        out, cap = self._start(cli="claude")
        cap.assert_not_called()
        self.assertNotIn("needs a price", out["error"])

    def test_capture_joins_wrapped_lines(self):
        done = subprocess.CompletedProcess([], 0, stdout="x\n")
        with mock.patch.object(tmux_backend.subprocess, "run", return_value=done) as run:
            tmux_backend.tmux_capture("p", lines=5, join=True)
            self.assertIn("-J", run.call_args[0][0])
            tmux_backend.tmux_capture("p", lines=5)
            self.assertNotIn("-J", run.call_args[0][0])


if __name__ == "__main__":
    unittest.main()

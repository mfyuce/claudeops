"""27 Kas (done20261127): yük altında ilk pencere geç kalınca tekrar deneme ikinci pencere açmasın.
Gerçek pencere açmaz, gerçek wmctrl/tmux çağırmaz."""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops import spawn  # noqa: E402


class WindowTitledTest(unittest.TestCase):
    def _run(self, out, rc=0):
        return mock.patch.object(spawn.subprocess, "run",
                                 return_value=subprocess.CompletedProcess([], rc, stdout=out, stderr=""))

    def test_exact_title_only(self):
        out = "0x01  0 host done20261127\n0x02  1 host done20261127_2\n0x03  0 host a b c\n"
        with self._run(out):
            self.assertTrue(spawn._window_titled("done20261127", ":1"))
            self.assertTrue(spawn._window_titled("a b c", ":1"))
            self.assertFalse(spawn._window_titled("done", ":1"))

    def test_unreadable_is_false(self):
        with self._run("", rc=1):
            self.assertFalse(spawn._window_titled("x", ":1"))
        self.assertFalse(spawn._window_titled("x", ""))
        with mock.patch.object(spawn.subprocess, "run", side_effect=FileNotFoundError("wmctrl")):
            self.assertFalse(spawn._window_titled("x", ":1"))


class WatchdogTest(unittest.TestCase):
    def _watch(self, window_exists, appear_after):
        calls = {"n": 0}

        def has_session(name):
            calls["n"] += 1
            return calls["n"] > appear_after
        with mock.patch.object(spawn, "FALLBACK_ATTEMPT_WAIT_SECONDS", 0.01), \
                mock.patch.object(spawn.time, "sleep"), \
                mock.patch.object(spawn, "tmux_has_session", side_effect=has_session), \
                mock.patch.object(spawn, "_window_titled", return_value=window_exists), \
                mock.patch.object(spawn, "_launch_gnome_terminal", return_value=True) as launch, \
                mock.patch.object(spawn, "tmux_spawn_direct", return_value=True) as direct, \
                mock.patch.object(spawn, "diag_log"):
            spawn._fallback_watchdog("s1", "/tmp", "inner", {"DISPLAY": ":1"}, "cmd")
        return launch, direct

    def test_existing_window_no_second_launch(self):
        launch, _ = self._watch(window_exists=True, appear_after=10 ** 9)
        launch.assert_not_called()

    def test_no_window_retries_as_before(self):
        launch, direct = self._watch(window_exists=False, appear_after=10 ** 9)
        self.assertEqual(launch.call_count, spawn.FALLBACK_RETRY_COUNT)
        direct.assert_called_once()


if __name__ == "__main__":
    unittest.main()

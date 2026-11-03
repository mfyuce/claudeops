"""862: detect_display `/tmp/.X11-unix/X<n>` soketini de tanır (Path.exists sahte; X YOK)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import spawn  # noqa: E402


def _exists_only(*paths):
    def fake(self):
        return str(self) in paths
    return fake


class DetectDisplayTest(unittest.TestCase):
    def _run(self, *existing):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPLAY", None)
            with mock.patch.object(Path, "exists", _exists_only(*existing)):
                return spawn.detect_display()

    def test_socket_only_x0(self):
        self.assertEqual(self._run("/tmp/.X11-unix/X0"), ":0")

    def test_lock_still_works(self):
        self.assertEqual(self._run("/tmp/.X1-lock"), ":1")

    def test_prefers_1_over_0(self):
        self.assertEqual(self._run("/tmp/.X11-unix/X0", "/tmp/.X11-unix/X1"), ":1")

    def test_nothing_defaults_1(self):
        self.assertEqual(self._run(), ":1")

    def test_env_wins(self):
        with mock.patch.dict(os.environ, {"DISPLAY": ":7"}):
            self.assertEqual(spawn.detect_display(), ":7")


if __name__ == "__main__":
    unittest.main()

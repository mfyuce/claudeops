import os
import stat
import tempfile
import unittest
from unittest import mock

from claudeops import settings


class ResolvedBinaryOverrideTest(unittest.TestCase):
    def _res(self, override):
        with mock.patch.object(settings, "load_settings", return_value={"provider_bin": {"x": override}}), \
                mock.patch.object(settings.shutil, "which", return_value="/usr/bin/x"):
            return settings.resolved_binary("x")

    def test_valid_executable_override_wins(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x")
            open(p, "w").write("#!/bin/sh\n")
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
            self.assertEqual(self._res(p), p)

    def test_tilde_expanded(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"HOME": d}):
            p = os.path.join(d, "x")
            open(p, "w").write("#!/bin/sh\n")
            os.chmod(p, 0o755)
            self.assertEqual(self._res("~/x"), p)

    def test_missing_or_non_executable_falls_back_to_path(self):
        self.assertEqual(self._res("/nonexistent/x"), "/usr/bin/x")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x")
            open(p, "w").write("data")
            os.chmod(p, 0o644)
            self.assertEqual(self._res(p), "/usr/bin/x")


if __name__ == "__main__":
    unittest.main()

"""L3 (10 Kas 2026): test koşucusu altında `CLAUDEOPS_DIR` hiçbir zaman canlı ~/.claude/claudeops olmaz (paths.py tek nokta)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import paths  # noqa: E402
from claudeops import diaglog, settings  # noqa: E402

LIVE = os.path.realpath(os.path.join(os.path.expanduser("~"), ".claude", "claudeops"))


class IsolationTest(unittest.TestCase):
    def test_state_dir_is_not_live_under_runner(self):
        for p in (paths.CLAUDEOPS_DIR, os.path.dirname(settings.SETTINGS_JSON), os.path.dirname(diaglog.diag_log_path())):
            self.assertNotEqual(os.path.realpath(p), LIVE, p)
        self.assertEqual(os.environ.get("CLAUDEOPS_DIR"), paths.CLAUDEOPS_DIR)   # alt süreçler de devralır

    def test_runner_detection(self):
        with mock.patch.object(sys, "argv", ["python3 -m unittest"]), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDEOPS_TEST_REAL_DIR", None)
            self.assertTrue(paths._under_test_runner())
            os.environ["CLAUDEOPS_TEST_REAL_DIR"] = "1"
            self.assertFalse(paths._under_test_runner())
        with mock.patch.object(sys, "argv", ["/usr/bin/cops"]), mock.patch.dict(sys.modules, {"pytest": None, "_pytest": None}):
            sys.modules.pop("pytest", None)
            sys.modules.pop("_pytest", None)
            self.assertFalse(paths._under_test_runner())


if __name__ == "__main__":
    unittest.main()

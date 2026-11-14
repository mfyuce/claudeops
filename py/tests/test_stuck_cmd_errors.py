import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import stuck as cmd  # noqa: E402


class StuckCmdErrors(unittest.TestCase):
    def run_with(self, result):
        info = SimpleNamespace(session=SimpleNamespace(name="x", pid=1, cpu=0.0, cli="claude"), last_role="user")
        args = SimpleNamespace(recover=True, dry_run=False, display=":0", grace=1.0, no_cpu=True, base=None)
        fn = cmd.run
        with mock.patch.object(cmd, "find_sessions", return_value=[]), mock.patch.object(cmd, "find_stuck", return_value=[info]), mock.patch.object(cmd, "recover_stuck", return_value=result), \
                mock.patch.object(cmd, "detect_display", return_value=":0"):
            return fn(args)

    def test_ok_results_are_zero_errors(self):
        self.assertEqual(self.run_with("recovered (tmux)"), 0)
        self.assertEqual(self.run_with("dry-run"), 0)

    def test_unexpected_result_counts_as_error(self):
        self.assertEqual(self.run_with("kill-failed"), 1)
        self.assertEqual(self.run_with("boom"), 1)


if __name__ == "__main__":
    unittest.main()

"""727: `_interactive_args` --interactive'i yalnız ikili tanıyorsa ekler (sahte yoklama; süreç YOK)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import ucli_provider as up  # noqa: E402


class InteractiveArgsTest(unittest.TestCase):
    def test_supported_adds_flag(self):
        with mock.patch.object(up, "binary_supports_flag", lambda b, f: f == "--interactive"):
            self.assertEqual(up._interactive_args("ucli", "s1"), ["--interactive"])

    def test_unsupported_skips_and_logs(self):
        logs = []
        with mock.patch.object(up, "binary_supports_flag", lambda b, f: False), \
                mock.patch.object(up, "diag_log", lambda *a, **k: logs.append((a, k))):
            self.assertEqual(up._interactive_args("ucli", "s1"), [])
        self.assertEqual(logs[0][0][0], "ucli_flag_unsupported")


if __name__ == "__main__":
    unittest.main()

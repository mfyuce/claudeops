import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops.providers import ucli_provider as up  # noqa: E402


def apply(opts):
    with mock.patch.object(up, "binary_supports_flag", lambda b, f: True), \
            mock.patch.object(up, "_default_session_cap", return_value=8.0), \
            mock.patch.object(up, "path_executables", return_value={}):
        return up._apply_cli_opts(["ucli", "chat"], opts)[0]


class EvrenNoDefaultCapTest(unittest.TestCase):
    def test_evren_has_no_default_cap(self):
        self.assertNotIn("--max-session-usd", apply({}))
        self.assertNotIn("--max-session-usd", apply({"service": "evren"}))

    def test_explicit_cap_on_evren_still_passes(self):
        argv = apply({"max_session_usd": 3})
        self.assertEqual(argv[argv.index("--max-session-usd") + 1], "3")


if __name__ == "__main__":
    unittest.main()

"""Pencere eylemlerinde panelden gelen model adı sondaki satır sonuyla spawn isteğine girmesin."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import window_actions as wa  # noqa: E402


class TrailingNewlineModelTest(unittest.TestCase):
    def test_model_with_newline_is_not_forwarded(self):
        status = {"sessions": [], "cli_options": {}, "settings": {}}
        row = {"cli": "claude", "running": True, "live_model": "claude-sonnet-5-5"}
        self.assertEqual(wa.spawn_fields(status, row, wa.LOCAL_HOST)["model"], "claude-sonnet-5-5")
        row["live_model"] = "claude-sonnet-5-5\n"
        self.assertEqual(wa.spawn_fields(status, row, wa.LOCAL_HOST)["model"], "")


if __name__ == "__main__":
    unittest.main()

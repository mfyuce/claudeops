import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import check, kill, mcp_queue  # noqa: E402


class KillCheckRobustTest(unittest.TestCase):
    def test_via_panel_falls_back_when_token_unreadable(self):
        with mock.patch.object(mcp_queue, "_api", side_effect=mcp_queue.ApiError("cannot read /x/web.token: nope")):
            self.assertIsNone(kill._via_panel(1, "a"))
        with mock.patch.object(mcp_queue, "_api", side_effect=mcp_queue.ApiError("HTTP 500 from claudeops panel")):
            self.assertEqual(kill._via_panel(1, "a")["ok"], False)

    def test_compile_all_survives_broken_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ok.py").write_text("x = 1\n")
            os.symlink(os.path.join(d, "yok.py"), os.path.join(d, "kirik.py"))
            errs = check.compile_all(Path(d))
            self.assertEqual(len(errs), 1)
            self.assertIn("kirik.py", errs[0])


if __name__ == "__main__":
    unittest.main()

"""`cli_install._seed_claude_tui_default`: ~/.claude/settings.json'a `tui` eklerken dosyanın iznini korur
(review 2026-11-04 deepseek R-1/R-03: `open(tmp, "w")` + `os.replace` 0600'ü umask'a düşürüyordu)."""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from claudeops import cli_install  # noqa: E402


class SeedKeepsMode(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"HOME": self.home})
        self.env.start()
        self.path = os.path.join(self.home, ".claude", "settings.json")

    def tearDown(self):
        self.env.stop()

    def mode(self):
        return stat.S_IMODE(os.stat(self.path).st_mode)

    def test_existing_0600_file_stays_0600(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"model": "x"}, f)
        os.chmod(self.path, 0o600)
        cli_install._seed_claude_tui_default()
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(json.load(open(self.path)), {"model": "x", "tui": "default"})
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.path)) if n.endswith(".tmp")], [])

    def test_new_file_is_private(self):
        cli_install._seed_claude_tui_default()
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(json.load(open(self.path)), {"tui": "default"})

    def test_explicit_tui_is_left_alone(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"tui": "fullscreen"}, f)
        before = open(self.path).read()
        cli_install._seed_claude_tui_default()
        self.assertEqual(open(self.path).read(), before)


if __name__ == "__main__":
    unittest.main()

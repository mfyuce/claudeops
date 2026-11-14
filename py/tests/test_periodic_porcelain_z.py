import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import periodic  # noqa: E402


class PorcelainZTest(unittest.TestCase):
    def test_plain_and_untracked(self):
        self.assertEqual(periodic._porcelain_z_paths("?? local/a b.jsonl\0 M memory/x.md\0"), ["local/a b.jsonl", "memory/x.md"])

    def test_rename_skips_old_path_record(self):
        out = periodic._porcelain_z_paths("R  local/new.jsonl\0local/old.jsonl\0?? memory/y.md\0")
        self.assertEqual(out, ["local/new.jsonl", "memory/y.md"])

    def test_empty(self):
        self.assertEqual(periodic._porcelain_z_paths(""), [])


if __name__ == "__main__":
    unittest.main()

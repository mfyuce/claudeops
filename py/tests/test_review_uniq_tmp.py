import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_review as wr  # noqa: E402


class UniqTmp(unittest.TestCase):
    def test_unique_per_call_and_keeps_dir_and_suffix(self):
        a, b = wr._uniq_tmp("/x/y/f.md"), wr._uniq_tmp("/x/y/f.md")
        self.assertNotEqual(a, b)
        for t in (a, b):
            self.assertTrue(t.startswith("/x/y/f.md.") and t.endswith(".tmp"))


if __name__ == "__main__":
    unittest.main()

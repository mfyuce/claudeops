import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.textutil import split_names  # noqa: E402


class SplitNames(unittest.TestCase):
    def test_comma_space_mixed_dedup_order(self):
        self.assertEqual(split_names(["a,b", "c", " d , a", ""]), ["a", "b", "c", "d"])

    def test_empty(self):
        self.assertEqual(split_names(None), [])
        self.assertEqual(split_names([",", " "]), [])

    def test_cli_commands_use_it(self):
        import inspect
        from claudeops.commands import kill, rc, close, handover, usage
        for m in (kill, rc, close, handover, usage):
            self.assertIn("split_names(args.names)", inspect.getsource(m), m.__name__)


if __name__ == "__main__":
    unittest.main()

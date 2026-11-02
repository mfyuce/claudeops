import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402


class AutoStart(unittest.TestCase):
    def test_default_true_and_field_exists(self):
        self.assertTrue(sw.Config().auto_start)

    def test_source_guard(self):
        # motorun cadence başlatması auto_start'a bağlı (`for p in (due if cfg.auto_start else [])`)
        src = open(os.path.join(os.path.dirname(sw.__file__), "steward.py"), encoding="utf-8").read()
        self.assertIn("for p in (due if cfg.auto_start else []):", src)


if __name__ == "__main__":
    unittest.main()

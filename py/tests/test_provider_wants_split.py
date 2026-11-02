"""TBD#50: has_conversation() -> wants_handover_wrapup() / wants_stuck_recovery(); ucli wrapup=False.

Çalıştırma:  python3 py/tests/test_provider_wants_split.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.providers import get_provider  # noqa: E402


class WantsSplitTests(unittest.TestCase):
    def test_ucli_no_wrapup_but_has_conversation_and_stuck(self):
        p = get_provider("ucli")
        self.assertTrue(p.has_conversation())
        self.assertFalse(p.wants_handover_wrapup())
        self.assertTrue(p.wants_stuck_recovery())

    def test_claude_defaults_follow_has_conversation(self):
        p = get_provider("claude")
        self.assertTrue(p.wants_handover_wrapup())
        self.assertTrue(p.wants_stuck_recovery())

    def test_shell_wants_nothing(self):
        p = get_provider("shell")
        self.assertFalse(p.has_conversation())
        self.assertFalse(p.wants_handover_wrapup())
        self.assertFalse(p.wants_stuck_recovery())


if __name__ == "__main__":
    unittest.main()

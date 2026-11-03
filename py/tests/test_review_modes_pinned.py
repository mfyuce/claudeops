"""GATE-TODO3 madde 8: review/izle mod listesi tek kaynaktan (review.MODES) gelir ve sabitlenir."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from claudeops import review as rv  # noqa: E402

_WR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "claudeops", "commands", "web_review.py")


class TestReviewModesPinned(unittest.TestCase):
    def test_modes_pinned(self):
        self.assertEqual(rv.MODES, ("agy", "evren", "claude", "codex", "copilot", "anthropic"))

    def test_default_slots_cover_every_mode(self):
        self.assertEqual(rv.parse_slots(""), {})      # belgelenmiş: boş = eski tek iş kipi
        self.assertEqual(set(rv.parse_slots("agy=1")), set(rv.MODES))

    def test_run_error_message_not_hardcoded(self):
        with open(_WR, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("agy|evren|claude|codex|copilot and model", src)
        self.assertIsNotNone(re.search(r'"mode must be " \+ "\|"\.join\(rv\.MODES\)', src))


if __name__ == "__main__":
    unittest.main()

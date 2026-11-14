import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_review as wr  # noqa: E402


class VerifyAgySlotTest(unittest.TestCase):
    def test_slot_per_cwd_stable_and_above_review_slots(self):
        a, b = wr.verify_agy_slot("/w/projA"), wr.verify_agy_slot("/w/projB")
        self.assertEqual(a, wr.verify_agy_slot("/w/projA"))
        self.assertNotEqual(a, b)
        for s in (a, b):
            self.assertTrue(100 <= s < 1100)


if __name__ == "__main__":
    unittest.main()

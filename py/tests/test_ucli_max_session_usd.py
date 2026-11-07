import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claudeops import ucli_session_opts as so


class MaxSessionUsd(unittest.TestCase):
    def test_valid_kept_as_float(self):
        out, err = so.validate_opts({"max_session_usd": "5,5"})
        self.assertEqual((out, err), ({"max_session_usd": 5.5}, ""))

    def test_zero_and_empty_dropped(self):
        for v in (0, "", None):
            self.assertEqual(so.validate_opts({"max_session_usd": v}), ({}, ""))

    def test_invalid_rejected(self):
        for v in ("x", -1, 5000):
            out, err = so.validate_opts({"max_session_usd": v})
            self.assertEqual(out, {})
            self.assertTrue(err)

    def test_independent_of_per_turn_cap(self):
        out, _ = so.validate_opts({"max_cost_usd": 2, "max_session_usd": 10})
        self.assertEqual(out, {"max_cost_usd": 2.0, "max_session_usd": 10.0})


if __name__ == "__main__":
    unittest.main()

"""TBD#384: uzaktan gelen durum degerleri ve yedek adres kurali kapali yone duser (Rust `cops-hosts` ile ayni)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_hosts as wh  # noqa: E402


class NonFiniteClockTest(unittest.TestCase):
    def test_non_finite_now_drops_fwd(self):
        for now in (float("nan"), float("inf"), "nan", "-inf"):
            self.assertIsNone(wh._fwd_brief({"mode": "accept", "now": now}, 1000.0), now)

    def test_result_is_strict_json(self):
        out = wh._finalize_remote_result("h", {"ok": True, "fwd": {"now": float("nan")}})
        json.dumps(out, allow_nan=False)
        self.assertTrue(out["ok"])


class KidsShapeTest(unittest.TestCase):
    def test_non_list_kids_drop_fwd(self):
        for kids in ("abc", {"a": 1}, 5, True):
            self.assertIsNone(wh._fwd_brief({"mode": "accept", "kids": kids}, 0.0), kids)

    def test_empty_and_list_kids_pass(self):
        for kids in (None, "", {}, 0, []):
            self.assertEqual(wh._fwd_brief({"kids": kids}, 0.0)["kids"], [], kids)
        self.assertEqual(wh._fwd_brief({"kids": ["a", 1]}, 0.0)["kids"], ["a", "1"])


if __name__ == "__main__":
    unittest.main()

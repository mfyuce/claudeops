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


class ListFieldsTest(unittest.TestCase):
    def test_non_list_values_become_empty(self):
        for bad in ("abc", {"a": 1}, 5, True):
            out = wh._finalize_remote_result("h", {"ok": True, "cli_list": bad, "dups": bad})
            self.assertEqual((out["cli_list"], out["dups"]), ([], []), bad)

    def test_lists_pass(self):
        out = wh._finalize_remote_result("h", {"ok": True, "cli_list": ["claude"], "dups": ["x"]})
        self.assertEqual((out["cli_list"], out["dups"]), (["claude"], ["x"]))


class PrivateLanTest(unittest.TestCase):
    def test_only_rfc1918_and_ula(self):
        for ok in ("10.0.0.1", "172.31.255.255", "192.168.0.1:8765", "[fd12::1]", "[::ffff:10.0.0.1]"):
            self.assertTrue(wh._is_private_lan_http(f"http://{ok}"), ok)
        for bad in ("198.18.0.1", "192.0.2.1", "203.0.113.5", "[2001:db8::1]", "172.32.0.1", "100.64.0.1", "8.8.8.8",
                    "127.0.0.1", "169.254.1.1", "0.0.0.0", "240.0.0.1", "[::1]", "[fe80::1]", "[::ffff:8.8.8.8]",
                    "[fd12::1%25eth0]"):
            self.assertFalse(wh._is_private_lan_http(f"http://{bad}"), bad)


if __name__ == "__main__":
    unittest.main()

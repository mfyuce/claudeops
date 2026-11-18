"""ucli sınır/ayar bayrakları (grup B): max_prompt_tokens, max_repeated_calls, max_consecutive_failures,
max_continuation_steps, exec_per_script, price, no_prompt_cache, show_usage. Doğrulama + argv + bayrak kapısı.
Gerçek Popen/ağ yok. Çalıştırılmadı (yazıldığı oturumda test koşturulamadı)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.ucli_session_opts import validate_opts  # noqa: E402

INTS = {
    "max_prompt_tokens": "--max-prompt-tokens",
    "max_repeated_calls": "--max-repeated-calls",
    "max_consecutive_failures": "--max-consecutive-failures",
    "max_continuation_steps": "--max-continuation-steps",
    "exec_per_script": "--exec-per-script",
}


def apply(opts, supports=lambda b, f: True):
    with mock.patch.object(up, "binary_supports_flag", supports), \
            mock.patch.object(up, "_default_session_cap", return_value=0):
        return up._apply_cli_opts(["ucli"], opts, "sess1", "/tmp", "")


class ValidateTests(unittest.TestCase):
    def test_empty_and_zero_drop_key(self):
        raw = {k: "" for k in INTS}
        raw.update({"price": "", "no_prompt_cache": False, "show_usage": "false"})
        self.assertEqual(validate_opts(raw), ({}, ""))
        self.assertEqual(validate_opts({k: "0" for k in INTS}), ({}, ""))

    def test_ints_accepted(self):
        out, err = validate_opts({"max_repeated_calls": "5", "max_prompt_tokens": 200000})
        self.assertEqual(err, "")
        self.assertEqual(out, {"max_repeated_calls": 5, "max_prompt_tokens": 200000})

    def test_ints_invalid_are_errors(self):
        for key in INTS:
            for bad in ("abc", "-1", "1.5", "999999999999"):
                out, err = validate_opts({key: bad})
                self.assertEqual(out, {}, (key, bad))
                self.assertIn(key, err)

    def test_bools(self):
        self.assertEqual(validate_opts({"show_usage": True, "no_prompt_cache": "true"}),
                         ({"show_usage": True, "no_prompt_cache": True}, ""))
        out, err = validate_opts({"show_usage": "maybe"})
        self.assertEqual(out, {})
        self.assertIn("show_usage", err)

    def test_price_two_and_four(self):
        self.assertEqual(validate_opts({"price": "3,15"}), ({"price": "3,15"}, ""))
        self.assertEqual(validate_opts({"price": " 3.5 , 15 , 0.3 , 3.75 "}), ({"price": "3.5,15,0.3,3.75"}, ""))

    def test_price_invalid(self):
        for bad in ("3", "3,15,1", "a,b", "0,15", "-1,5", "3,,15", "1,2,3,4,5", "3,15000", "3,nan"):
            out, err = validate_opts({"price": bad})
            self.assertEqual(out, {}, bad)
            self.assertIn("price", err)


class ArgvTests(unittest.TestCase):
    def test_nothing_by_default(self):
        argv, _ = apply({})
        # tek varsayılan bayrak: --usage-log (Claude dışı hizmetler dahil tüm açılışlar, 18 Kas Evren dersi); başka sınır bayrağı yok
        self.assertEqual(argv[:2], ["ucli", "--usage-log"])
        self.assertEqual(len(argv), 3)
        self.assertTrue(argv[2].endswith("/other/sess1.jsonl"))

    def test_int_flags_with_values(self):
        for key, flag in INTS.items():
            argv, _ = apply({key: 7})
            self.assertEqual(argv[argv.index(flag) + 1], "7", flag)
            self.assertEqual(argv.count(flag), 1)

    def test_price_and_bools(self):
        argv, _ = apply({"price": "3,15", "no_prompt_cache": True, "show_usage": True})
        self.assertEqual(argv[argv.index("--price") + 1], "3,15")
        self.assertEqual(argv.count("--no-prompt-cache"), 1)
        self.assertEqual(argv.count("--show-usage"), 1)

    def test_unsupported_flag_is_skipped_not_fatal(self):
        argv, _ = apply({"max_prompt_tokens": 5, "show_usage": True, "price": "1,2"}, supports=lambda b, f: False)
        self.assertEqual(argv, ["ucli"])

    def test_only_supported_ones_added(self):
        argv, _ = apply({"max_prompt_tokens": 5, "show_usage": True}, supports=lambda b, f: f == "--show-usage")
        self.assertIn("--show-usage", argv)
        self.assertNotIn("--max-prompt-tokens", argv)


if __name__ == "__main__":
    unittest.main()

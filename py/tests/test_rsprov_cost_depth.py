"""rs/prov: aşırı derin harcama satırı. Toplam, tavan ve inceleme bütçe kapısı aynı sınırda aynı karara varır (Rust:
`cops-providers/tests/usage_two_copies.rs`). Her şey geçici dizinde."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import review as rv, ucli_cost  # noqa: E402


def _deep(levels, inner="", ms=None):
    """Kayıt nesnesiyle birlikte `levels` katlı istek satırı."""
    return '{"t": %d, "usage": {"input_tokens": 1000}, "x": %s%s%s}' % (
        time.time() * 1000 if ms is None else ms, "[" * (levels - 1), inner, "]" * (levels - 1))


class _Dir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.base = os.path.join(self.root, "ucli_usage")
        os.makedirs(self.base)
        self.events = []
        for p in (mock.patch.object(rv, "diag_log", lambda event, **k: self.events.append(k.get("what"))),
                  mock.patch.object(ucli_cost, "read_dirs", lambda base: [base])):
            p.start()
            self.addCleanup(p.stop)
        rv._BAD_SEEN.clear()
        ucli_cost.invalidate()
        ucli_cost._RESERVED.clear()
        self.addCleanup(rv._BAD_SEEN.clear)
        self.addCleanup(ucli_cost.invalidate)
        self.addCleanup(ucli_cost._RESERVED.clear)

    def put(self, text, *parts):
        path = os.path.join(*(parts or (self.base, "a.jsonl")))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        return path

    def cap(self, cap):
        return mock.patch.object(ucli_cost, "ucli_cost_config",
                                 lambda: {"daily_cap_usd": cap, "credit_total_usd": 0.0, "cache_ttl": "5m"})


class DepthLimit(_Dir):
    def test_the_deepest_countable_line_is_summed(self):
        for inner in ("", "1"):
            path = self.put(_deep(512, inner))
            usd, problem = rv._scan_usage(path, "", 0.0, 1.0)
            self.assertGreater(usd, 0, inner)
            self.assertEqual(problem, "", inner)

    def test_deeper_lines_are_not_summed_and_close_an_open_cap(self):
        for levels, inner in ((513, ""), (513, "1"), (700, ""), (5000, "")):
            rv._BAD_SEEN.clear()
            self.events.clear()
            path = self.put(_deep(levels, inner))
            self.assertEqual(rv._scan_usage(path, "", 0.0, 1.0), (0.0, "çok derin satır"), levels)
            self.assertEqual(self.events, ["usage.depth"])
            with self.cap(100.0), self.assertRaises(ValueError) as cm:
                ucli_cost.reserve("s", base=self.base)
            self.assertIn("çok derin satır", str(cm.exception))
            self.assertEqual(ucli_cost._RESERVED, {})
            with self.cap(0.0):
                ucli_cost.reserve("s", base=self.base)

    def test_torn_deep_line_closes_the_cap_too(self):
        path = self.put("[" * 100000)
        self.assertEqual(rv._scan_usage(path, "", 0.0, 1.0), (0.0, "çok derin satır"))

    def test_brackets_inside_strings_are_not_depth(self):
        many = "[{" * 600
        whole = json.dumps({"usage": {"input_tokens": 1000}, "note": 'a"\\' + many})
        for line in (whole, whole[:-3], '{"note": "' + many):
            self.assertEqual(rv._scan_usage(self.put(line), "", 0.0, 1.0)[1], "", line[:40])
        self.assertGreater(rv.usage_cost_usd(self.put(whole), ""), 0)

    def test_many_shallow_containers_are_not_depth(self):
        line = json.dumps({"usage": {"input_tokens": 1000}, "x": [[], {}] * 600})
        usd, problem = rv._scan_usage(self.put(line), "", 0.0, 1.0)
        self.assertGreater(usd, 0)
        self.assertEqual(problem, "")

    def test_recursion_error_inside_the_limit_is_not_silent(self):
        path = self.put(_deep(3))
        stub = mock.Mock(JSONDecodeError=json.JSONDecodeError,      # yalnız `review`in gördüğü `json`
                         **{"loads.side_effect": RecursionError})
        with mock.patch.object(rv, "json", stub):
            self.assertEqual(rv._scan_usage(path, "", 0.0, 1.0), (0.0, "çok derin satır"))


class LongIntegers(_Dir):
    """Python 4300 basamaktan uzun tam sayıyı ayrıştırmaz: satır eskiden sessizce 0 sayılıyordu."""

    def line(self, number):
        return '{"usage": {"input_tokens": 1000}, "x": %s}' % number

    def test_a_longer_integer_is_not_silent(self):
        if not hasattr(sys, "set_int_max_str_digits"):
            self.skipTest("bu yorumlayıcıda basamak sınırı yok")
        for number in ("9" * 4301, "-" + "9" * 4301):
            rv._BAD_SEEN.clear()
            self.events.clear()
            self.assertEqual(rv._scan_usage(self.put(self.line(number)), "", 0.0, 1.0), (0.0, "çok uzun sayı"))
            self.assertEqual(self.events, ["usage.number"])
            with self.cap(100.0), self.assertRaises(ValueError):
                ucli_cost.reserve("s", base=self.base)

    def test_countable_numbers_are_unchanged(self):
        long = "9" * 4301
        for number in ("9" * 4300, long + ".5", "1." + long, long + "e-4300", '"%s"' % long):
            usd, problem = rv._scan_usage(self.put(self.line(number)), "", 0.0, 1.0)
            self.assertGreater(usd, 0, number[:20])
            self.assertEqual(problem, "", number[:20])

    def test_a_broken_line_stays_a_torn_line(self):
        self.assertEqual(rv._scan_usage(self.put('{"usage": {"input_tokens": 1'), "", 0.0, 1.0), (0.0, ""))

    def test_it_closes_the_review_budget(self):
        if not hasattr(sys, "set_int_max_str_digits"):
            self.skipTest("bu yorumlayıcıda basamak sınırı yok")
        reviews = os.path.join(self.root, "reviews")
        self.put(self.line("9" * 4301), reviews, "p", "anthropic", "claude-sonnet-5-5", "a.usage.jsonl")
        self.assertEqual(rv.anthropic_spent_usd(reviews), rv._UNCOUNTABLE_SPENT_USD)


class ReviewBudgetGate(_Dir):
    def spent(self, *lines):
        reviews = os.path.join(self.root, "reviews")
        self.put("\n".join(lines), reviews, "p", "anthropic", "claude-sonnet-5-5", "a.usage.jsonl")
        return rv.anthropic_spent_usd(reviews)

    def test_countable_logs_sum_as_before(self):
        self.assertGreater(self.spent(_deep(512)), 0)
        self.assertLess(self.spent(_deep(512)), 1)

    def test_an_uncountable_line_closes_the_budget(self):
        got = self.spent(_deep(3), _deep(513))
        self.assertEqual(got, rv._UNCOUNTABLE_SPENT_USD)
        json.dumps(got, allow_nan=False)
        self.assertEqual(self.events, ["usage.depth"])

    def test_a_later_problem_does_not_reopen_it(self):
        got = self.spent(_deep(513), '{"t": "x", "usage": {"input_tokens": 1}}')
        self.assertEqual(got, rv._UNCOUNTABLE_SPENT_USD)


if __name__ == "__main__":
    unittest.main()

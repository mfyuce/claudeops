"""rs/prov: 16 MiB'tan uzun harcama satırı. Toplam, açık günlük tavan ve inceleme bütçe kapısı defterle aynı karara
varır (şüphede ret) ve satır sınırsız belleğe alınmaz (Rust: `cops-review-core` `usage::next_line`,
`cops-providers/tests/usage_two_copies.rs`). Her şey geçici dizinde."""
import json
import os
import sys
import tempfile
import time
import tracemalloc
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import review as rv, ucli_cost  # noqa: E402

LIMIT = 16 << 20        # satır sonu hariç bayt


def _line(size=0, tokens=1000):
    """Satır sonu HARİÇ tam `size` baytlık istek satırı (0 = dolgusuz)."""
    head = '{"t": %d, "usage": {"input_tokens": %d}, "x": "' % (time.time() * 1000, tokens)
    pad = max(0, size - len(head) - 2)
    return (head + "x" * pad + '"}').encode()


class _Dir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.base = os.path.join(self.root, "ucli_usage")
        os.makedirs(self.base)
        self.reviews = os.path.join(self.root, "reviews")
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

    def put(self, data, *parts):
        path = os.path.join(*(parts or (self.base, "a.jsonl")))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def review_log(self, data):
        return self.put(data, self.reviews, "p", "anthropic", "claude-sonnet-5-5", "a.usage.jsonl")

    def cap(self, cap):
        return mock.patch.object(ucli_cost, "ucli_cost_config",
                                 lambda: {"daily_cap_usd": cap, "credit_total_usd": 0.0, "cache_ttl": "5m"})


class LineLimit(_Dir):
    def test_a_line_of_exactly_the_limit_is_summed(self):
        for end in (b"\n", b""):                    # satır sonu olsa da olmasa da
            line = _line(LIMIT)
            self.assertEqual(len(line), LIMIT)
            usd, problem = rv._scan_usage(self.put(line + end), "", 0.0, 1.0)
            self.assertGreater(usd, 0, end)
            self.assertEqual(problem, "", end)
        self.assertEqual(self.events, [])

    def test_one_byte_more_is_not_summed_and_the_next_line_is(self):
        one = rv.usage_cost_usd(self.put(_line() + b"\n"), "")
        for data, want in ((_line(LIMIT + 1) + b"\n", 0.0), (_line(LIMIT + 1), 0.0),
                           (_line(LIMIT + 1) + b"\n" + _line() + b"\n", one),
                           (_line() + b"\n" + _line(LIMIT + 1), one)):
            rv._BAD_SEEN.clear()
            self.events.clear()
            self.assertEqual(rv._scan_usage(self.put(data), "", 0.0, 1.0), (want, "çok uzun satır"), len(data))
            self.assertEqual(self.events, ["usage.length"])

    def test_an_open_cap_refuses_and_no_cap_does_not(self):
        self.put(_line(LIMIT + 1) + b"\n")
        with self.cap(100.0), self.assertRaises(ValueError) as cm:
            ucli_cost.reserve("s", base=self.base)
        self.assertIn("çok uzun satır", str(cm.exception))
        self.assertEqual(ucli_cost._RESERVED, {})
        with self.cap(0.0):
            ucli_cost.reserve("s", base=self.base)

    def test_the_review_budget_closes(self):
        self.review_log(_line(LIMIT))
        self.assertLess(rv.anthropic_spent_usd(self.reviews), 1)
        self.review_log(_line() + b"\n" + _line(LIMIT + 1))
        got = rv.anthropic_spent_usd(self.reviews)
        self.assertEqual(got, rv._UNCOUNTABLE_SPENT_USD)
        json.dumps(got, allow_nan=False)

    def test_a_later_problem_does_not_reopen_the_budget(self):
        self.review_log(_line(LIMIT + 1) + b'\n{"t": "x", "usage": {"input_tokens": 1}}\n')
        self.assertEqual(rv.anthropic_spent_usd(self.reviews), rv._UNCOUNTABLE_SPENT_USD)


class Streaming(_Dir):
    def test_a_huge_line_is_not_held_in_memory(self):
        path = os.path.join(self.base, "a.jsonl")
        block = b"x" * (1 << 20)
        with open(path, "wb") as f:
            for _ in range(160):                    # satır sonu olmayan 160 MiB, sonra geçerli bir satır
                f.write(block)
            f.write(b"\n" + _line() + b"\n")
            for _ in range(160):                    # ve dosya sonuna dek biten satırı olmayan 160 MiB
                f.write(block)
        del block
        tracemalloc.start()
        try:
            usd, problem = rv._scan_usage(path, "", 0.0, 1.0)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertGreater(usd, 0)
        self.assertEqual(problem, "çok uzun satır")
        self.assertLess(peak, 3 * LIMIT)


if __name__ == "__main__":
    unittest.main()

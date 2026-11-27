"""ucli `--usage-log`: `task_end` satırı görevin TOPLAM `usage`ını yineler; maliyet yalnız istek satırlarından sayılır
(26 Kas denemesi: tek turluk Sonnet ajanı 0,032 USD yerine 0,052 göründü). Haiku 5.5 100K üstü istem pahalı dilimden."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import review as rv  # noqa: E402


def cost(records, model="", write_mult=1.0):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in records))
        return rv.usage_cost_usd(p, model, write_mult=write_mult)


# 26 Kas gerçek kaydı (alan adları ve sayılar aynen)
REAL = [
    {"event": "task_start", "model": "claude-sonnet-5-5", "t": 1, "task": 1},
    {"event": "request", "kind": "round", "t": 2, "task": 1,
     "usage": {"cache_creation_input_tokens": 7989, "cache_read_input_tokens": 0, "cached_tokens": 0,
               "completion_tokens": 5, "prompt_tokens": 7993}},
    {"event": "task_end", "ok": True, "t": 3, "task": 1,
     "usage": {"cached_tokens": 0, "completion_tokens": 5, "prompt_tokens": 7993, "requests": 1}},
]


def haiku(prompt):
    return [{"event": "request", "t": 1, "usage": {"cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                                                    "prompt_tokens": prompt, "completion_tokens": 1000}}]


class TaskEndNotCountedTest(unittest.TestCase):
    def test_task_end_total_is_not_billed_again(self):
        self.assertAlmostEqual(cost(REAL), (4 * 2.0 + 5 * 10.0 + 7989 * 2.5) / 1e6, places=9)

    def test_one_hour_write(self):
        self.assertAlmostEqual(cost(REAL, write_mult=1.6), (4 * 2.0 + 5 * 10.0 + 7989 * 4.0) / 1e6, places=9)


class HaikuTierTest(unittest.TestCase):
    def test_up_to_100k_is_the_cheap_tier(self):
        self.assertAlmostEqual(cost(haiku(100_000), "claude-haiku-5-5"), (100_000 * 0.10 + 1000 * 0.50) / 1e6, places=9)

    def test_above_100k_is_the_expensive_tier(self):
        self.assertAlmostEqual(cost(haiku(100_001), "claude-haiku-5-5"), (100_001 * 0.50 + 1000 * 2.50) / 1e6, places=9)

    def test_cached_tokens_count_toward_the_threshold(self):
        r = haiku(100_001)
        r[0]["usage"]["cache_read_input_tokens"] = 100_000
        self.assertAlmostEqual(cost(r, "claude-haiku-5-5"), (1 * 0.50 + 100_000 * 0.05 + 1000 * 2.50) / 1e6, places=9)

    def test_tier_is_per_request_not_summed(self):
        self.assertAlmostEqual(cost(haiku(60_000) * 2, "claude-haiku-5-5"), 2 * (60_000 * 0.10 + 1000 * 0.50) / 1e6,
                               places=9)


if __name__ == "__main__":
    unittest.main()

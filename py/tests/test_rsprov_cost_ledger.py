"""rs/prov G8 ikinci parça: maliyet defteri (`ucli_cost`, `review.usage_cost_usd`) bozuk/okunamayan günlükte. Her şey geçici dizinde."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import review as rv  # noqa: E402
from claudeops import ucli_cost  # noqa: E402


def _line(usage=None, **kw):
    rec = {"t": time.time() * 1000.0, "usage": usage or {"prompt_tokens": 1_000_000, "completion_tokens": 0}}
    rec.update(kw)
    return json.dumps(rec) + "\n"


class _Ledger(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = tmp.name
        ucli_cost.invalidate()
        ucli_cost._RESERVED.clear()
        self.addCleanup(ucli_cost.invalidate)
        self.addCleanup(ucli_cost._RESERVED.clear)

    def put(self, name, data):
        path = os.path.join(self.base, name)
        with open(path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        return path

    def cap(self, cap):
        return mock.patch.object(ucli_cost, "ucli_cost_config",
                                 lambda: {"daily_cap_usd": cap, "credit_total_usd": 0.0, "cache_ttl": "5m"})


class UnreadableLinesDoNotRaise(_Ledger):
    def one(self):
        return rv.usage_cost_usd(self.put("ref.jsonl", _line()), "")

    def test_bad_utf8_byte_keeps_the_other_records(self):
        one = self.one()
        path = self.put("a.jsonl", b"\xff\xfe\n" + _line().encode() + b'{"t": 1, "note": "\xc4')
        self.assertAlmostEqual(rv.usage_cost_usd(path, ""), one)
        with self.cap(0.0):
            self.assertGreater(ucli_cost.state(base=self.base, use_cache=False)["today_usd"], 0)

    def test_huge_numbers_and_deep_nesting_do_not_raise(self):
        one = self.one()
        huge = "1" + "0" * 400
        path = self.put("a.jsonl", '{"t": %s, "usage": {"prompt_tokens": 1}}\n' % huge
                        + '{"usage": {"prompt_tokens": %s}}\n' % huge + "[" * 100000 + "\n" + _line())
        self.assertAlmostEqual(rv.usage_cost_usd(path, ""), one, places=4)


if __name__ == "__main__":
    unittest.main()

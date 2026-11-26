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


class InvalidCountsNeverLowerTheSpend(_Ledger):
    def test_nan_infinite_and_negative_counts_are_not_summed(self):
        good = rv.usage_cost_usd(self.put("ref.jsonl", _line()), "")
        for bad in ("NaN", "Infinity", "-Infinity", "-5000000", "1e300", "true", '"7"'):
            path = self.put("a.jsonl", _line() + '{"t": %d, "usage": {"completion_tokens": %s}}\n' % (time.time() * 1000, bad))
            self.assertEqual(rv.usage_cost_usd(path, ""), good, bad)

    def test_open_cap_refuses_a_ledger_with_an_invalid_value(self):
        for body in ('{"t": %d, "usage": {"completion_tokens": NaN}}\n',
                     '{"t": %d, "usage": {"prompt_tokens": -1000000}}\n',
                     '{"t": %d, "usage": {"input_tokens": "12"}}\n',
                     '{"t": "yarin%d", "usage": {"prompt_tokens": 1}}\n'):
            self.put("a.jsonl", body % (time.time() * 1000))
            with self.cap(10.0), self.assertRaises(ValueError) as cm:
                ucli_cost.reserve("s", base=self.base)
            self.assertNotIsInstance(cm.exception, ucli_cost.DailyCapExceeded)
            self.assertIn("denetlenemiyor", str(cm.exception))
            self.assertEqual(ucli_cost._RESERVED, {})
        with self.cap(0.0):
            ucli_cost.reserve("s", base=self.base)      # tavan kapalı: denetim yok

    def test_torn_lines_null_counts_and_old_files_do_not_block(self):
        self.put("a.jsonl", _line({"prompt_tokens": 10, "cached_tokens": None}) + '{"t": 5, "usage": {"prompt_to\n[]\n{"usage": null}\n')
        old = self.put("old.jsonl", '{"t": 1, "usage": {"prompt_tokens": -1}}\n')
        os.utime(old, (time.time() - 3 * 86400,) * 2)
        with self.cap(10.0):
            ucli_cost.reserve("s", base=self.base)


class UnreadableLedgerClosesTheGate(_Ledger):
    def refuse(self):
        with self.cap(10.0), self.assertRaises(ValueError) as cm:
            ucli_cost.reserve("s", base=self.base)
        self.assertIn("denetlenemiyor", str(cm.exception))

    @unittest.skipIf(os.getuid() == 0, "root izinleri aşar")
    def test_unreadable_file(self):
        path = self.put("a.jsonl", _line())
        os.chmod(path, 0)
        self.refuse()

    @unittest.skipIf(os.getuid() == 0, "root izinleri aşar")
    def test_unreadable_directory(self):
        os.chmod(self.base, 0o300)
        self.addCleanup(os.chmod, self.base, 0o700)
        self.refuse()

    def test_directory_that_is_a_file(self):
        self.base = self.put("f", "x")
        self.refuse()

    def test_directory_named_like_a_log(self):
        os.mkdir(os.path.join(self.base, "d.jsonl"))
        self.refuse()

    def test_fifo_neither_blocks_nor_passes(self):
        os.mkfifo(os.path.join(self.base, "p.jsonl"))
        done = []
        t = threading.Thread(target=lambda: done.append(self.refuse()), daemon=True)
        t.start()
        t.join(5)
        blocked = t.is_alive()
        deadline = time.monotonic() + 10
        while t.is_alive() and time.monotonic() < deadline:     # eski davranışta bloklanan okuyucuları serbest bırak
            try:
                os.close(os.open(os.path.join(self.base, "p.jsonl"), os.O_WRONLY | os.O_NONBLOCK))
            except OSError:
                pass
            t.join(0.01)
        self.assertFalse(blocked)
        self.assertEqual(len(done), 1)

    def test_missing_directory_is_zero_spend(self):
        with self.cap(10.0):
            ucli_cost.reserve("s", base=os.path.join(self.base, "yok"))


class InvalidateRace(_Ledger):
    def test_invalidate_between_scan_and_read_does_not_zero_the_spend(self):
        zero = {"at": 0.0, "usd": 0.0, "total": 0.0, "by": {}, "day": "", "rate_1h": {}, "rate_15m": {}}

        class Racing(dict):
            def update(self, *a, **kw):
                super().update(*a, **kw)
                if kw.get("by"):
                    super().update(zero)       # tam bu anda başka iş parçacığı `invalidate()` çağırdı

        self.put("a.jsonl", _line())
        with mock.patch.object(ucli_cost, "_CACHE", Racing(zero)), self.cap(0.5):
            self.assertTrue(ucli_cost.cap_exceeded(base=self.base))


if __name__ == "__main__":
    unittest.main()

"""ucli_cost.reserve: eşanlı başlatmalarda tavan rezervasyonu (P4-VERDICT #34) — stdlib unittest."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_cost  # noqa: E402


class ReserveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = self._tmp.name
        ucli_cost._RESERVED.clear()
        self.addCleanup(ucli_cost._RESERVED.clear)

    def cfg(self, cap):
        return mock.patch.object(ucli_cost, "ucli_cost_config",
                                 lambda: {"daily_cap_usd": cap, "credit_total_usd": 0.0, "cache_ttl": "1h"})

    def test_two_sessions_cap_two(self):
        with self.cfg(2.0):
            ucli_cost.reserve("a", now=1000.0, base=self.base)      # 0 + 0 < 2
            ucli_cost.reserve("b", now=1000.0, base=self.base)      # 0 + 1 < 2
            with self.assertRaises(ucli_cost.DailyCapExceeded):
                ucli_cost.reserve("c", now=1000.0, base=self.base)  # 0 + 2 >= 2

    def test_same_name_replaces(self):
        with self.cfg(2.0):
            ucli_cost.reserve("a", now=1000.0, base=self.base)
            ucli_cost.reserve("a", now=1001.0, base=self.base)
            self.assertEqual(len(ucli_cost._RESERVED), 1)

    def test_release_frees_slot(self):
        with self.cfg(1.0):
            ucli_cost.reserve("a", now=1000.0, base=self.base)
            with self.assertRaises(ucli_cost.DailyCapExceeded):
                ucli_cost.reserve("b", now=1000.0, base=self.base)
            ucli_cost.release("a")
            ucli_cost.reserve("b", now=1000.0, base=self.base)

    def test_ttl_expiry(self):
        with self.cfg(1.0):
            ucli_cost.reserve("a", now=1000.0, base=self.base)
            ucli_cost.reserve("b", now=1000.0 + ucli_cost.RESERVE_TTL + 1, base=self.base)

    def test_no_cap_keeps_nothing(self):
        with self.cfg(0.0):
            ucli_cost.reserve("a", now=1000.0, base=self.base)
            self.assertEqual(ucli_cost._RESERVED, {})


if __name__ == "__main__":
    unittest.main()

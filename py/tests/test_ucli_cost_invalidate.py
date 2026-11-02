"""ucli_cost.invalidate: ayar kaydı sonrası 30 sn önbellek düşer — stdlib unittest.

Çalıştırma:  python3 py/tests/test_ucli_cost_invalidate.py -v
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_cost  # noqa: E402


class TestInvalidate(unittest.TestCase):
    def test_invalidate_forces_rescan(self):
        cfg = {"daily_cap_usd": 5, "cache_ttl": "1h"}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ucli_cost, "ucli_cost_config", lambda: cfg), \
                mock.patch.object(ucli_cost, "today_usd") as tu:
            tu.return_value = 1.0
            ucli_cost.invalidate()
            ucli_cost.state(base=d)
            ucli_cost.state(base=d)
            self.assertEqual(tu.call_count, 1)      # ikincisi önbellekten
            ucli_cost.invalidate()
            tu.return_value = 2.0
            st = ucli_cost.state(base=d)
            self.assertEqual(tu.call_count, 2)
            self.assertEqual(st["today_usd"], 2.0)
            self.assertEqual(st["cap_usd"], 5.0)
        ucli_cost.invalidate()


if __name__ == "__main__":
    unittest.main()

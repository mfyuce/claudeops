import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_cost  # noqa: E402


class WriteMult(unittest.TestCase):
    def test_1h(self):
        with mock.patch.object(ucli_cost, "ucli_cost_config", return_value={"cache_ttl": "1h"}):
            self.assertEqual(ucli_cost.write_mult(), 1.6)

    def test_other(self):
        with mock.patch.object(ucli_cost, "ucli_cost_config", return_value={"cache_ttl": "5m"}):
            self.assertEqual(ucli_cost.write_mult(), 1.0)


if __name__ == "__main__":
    unittest.main()

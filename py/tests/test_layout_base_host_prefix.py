"""657: `_base_from_name` `host:ad` mirror başlığında host önekini yok sayar (saf; X/ağ YOK)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.layout import _base_from_name  # noqa: E402


class BaseFromNameTest(unittest.TestCase):
    def test_bare_name(self):
        self.assertEqual(_base_from_name("hc54"), "hc")
        self.assertEqual(_base_from_name("anomaly"), "anomaly")

    def test_host_prefix_ignored(self):
        self.assertEqual(_base_from_name("yuhem:hc54"), "hc")
        self.assertEqual(_base_from_name("local:hc54"), "hc")

    def test_host_prefix_without_digits_returns_name_part(self):
        self.assertEqual(_base_from_name("ulak_31:oiso"), "oiso")

    def test_trailing_colon_keeps_whole_name(self):
        self.assertEqual(_base_from_name("host:"), "host:")


if __name__ == "__main__":
    unittest.main()

"""`steward ... history/list` zaman sütunu: 1 dakikadan kısa süre saniye gösterir (stdlib unittest)."""
import time
import unittest
from unittest import mock

from claudeops.commands import steward as cs


class AgoTest(unittest.TestCase):
    def test_units(self):
        with mock.patch.object(cs.time, "time", return_value=1_000_000.0):
            self.assertEqual(cs._ago(1_000_000.0 - 42), "42sn")
            self.assertEqual(cs._ago(1_000_000.0), "0sn")
            self.assertEqual(cs._ago(1_000_000.0 + 5), "0sn")       # saat kayması eksi göstermez
            self.assertEqual(cs._ago(1_000_000.0 - 60), "1dk")
            self.assertEqual(cs._ago(1_000_000.0 - 3600), "1s")
            self.assertEqual(cs._ago(1_000_000.0 - 86400), "1g")
            self.assertEqual(cs._ago(0), "-")


if __name__ == "__main__":
    unittest.main()

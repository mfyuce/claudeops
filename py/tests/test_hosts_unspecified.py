"""P1: 0.0.0.0 / :: (ve v4-mapped) host olarak engellenir; getaddrinfo ağa çıkmaz (literal IP)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import hosts  # noqa: E402


class UnspecifiedBlockedTest(unittest.TestCase):
    def test_unspecified_literals_are_blocked(self):
        for url in ("http://0.0.0.0:8080", "http://[::]:8080", "http://[::ffff:0.0.0.0]:80"):
            self.assertTrue(hosts._host_is_blocked(url), url)

    def test_loopback_still_blocked(self):
        self.assertTrue(hosts._host_is_blocked("http://127.0.0.1:1"))


if __name__ == "__main__":
    unittest.main()

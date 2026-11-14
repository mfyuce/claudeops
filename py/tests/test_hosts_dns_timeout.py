import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import hosts  # noqa: E402


class DnsTimeout(unittest.TestCase):
    def test_hung_resolution_does_not_block_and_fails_open(self):
        with mock.patch.object(hosts.socket, "getaddrinfo", side_effect=lambda *a, **k: time.sleep(5)):
            with mock.patch.object(hosts, "DNS_CHECK_TIMEOUT", 0.2):
                t0 = time.monotonic()
                self.assertFalse(hosts._host_is_blocked("http://yavas.example:8765"))
                self.assertLess(time.monotonic() - t0, 2)

    def test_loopback_still_blocked_and_gaierror_fails_open(self):
        self.assertTrue(hosts._host_is_blocked("http://127.0.0.1:8765"))
        self.assertTrue(hosts._host_is_blocked("http://2130706433/"))
        import socket
        with mock.patch.object(hosts.socket, "getaddrinfo", side_effect=socket.gaierror):
            self.assertFalse(hosts._host_is_blocked("http://yok.example"))


if __name__ == "__main__":
    unittest.main()

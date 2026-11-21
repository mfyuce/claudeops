import unittest
from claudeops.commands.web import trusted_forwarded_ip as t


class H(dict):
    def get(self, k, d=None):
        return super().get(k, d)


class XFF(unittest.TestCase):
    def test_no_secret_ignores_header(self):
        self.assertEqual(t("127.0.0.1", H({"X-Forwarded-For": "9.9.9.9"}), ""), "127.0.0.1")

    def test_wrong_or_missing_secret(self):
        self.assertEqual(t("127.0.0.1", H({"X-Forwarded-For": "9.9.9.9", "X-Cops-Front": "x"}), "s"), "127.0.0.1")
        self.assertEqual(t("127.0.0.1", H({"X-Forwarded-For": "9.9.9.9"}), "s"), "127.0.0.1")

    def test_non_loopback_peer_never_trusted(self):
        self.assertEqual(t("10.0.0.5", H({"X-Forwarded-For": "9.9.9.9", "X-Cops-Front": "s"}), "s"), "10.0.0.5")

    def test_valid_secret_uses_last_xff(self):
        self.assertEqual(t("127.0.0.1", H({"X-Forwarded-For": "6.6.6.6, 1.2.3.4", "X-Cops-Front": "s"}), "s"), "1.2.3.4")
        self.assertEqual(t("::1", H({"X-Cops-Front": "s"}), "s"), "::1")

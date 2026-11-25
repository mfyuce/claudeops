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

    def test_tunnel_client_ip_only_from_loopback(self):
        cf = {"Cf-Connecting-IP": "203.0.113.7"}
        self.assertEqual(t("127.0.0.1", H(cf), ""), "203.0.113.7")
        self.assertEqual(t("10.0.0.5", H(cf), ""), "10.0.0.5")
        front = {**cf, "X-Cops-Front": "s"}
        self.assertEqual(t("127.0.0.1", H({**front, "X-Forwarded-For": "127.0.0.1"}), "s"), "203.0.113.7")   # tünel -> copsd
        self.assertEqual(t("127.0.0.1", H({**front, "X-Forwarded-For": "10.0.0.5"}), "s"), "10.0.0.5")       # uzak -> copsd
        self.assertEqual(t("127.0.0.1", H({"Cf-Connecting-IP": "1.1.1.1|*"}), ""), "127.0.0.1")

    def test_route_request_uses_trusted_ip(self):
        from claudeops.extensions import RouteRequest

        class Fake:
            path, client_address = "/api/auth/login", ("127.0.0.1", 1)

            def _client_ip(self):
                return "203.0.113.7"
        self.assertEqual(RouteRequest(Fake(), "POST", Fake.path).client_addr, "203.0.113.7")

    def test_valid_secret_uses_last_xff(self):
        self.assertEqual(t("127.0.0.1", H({"X-Forwarded-For": "6.6.6.6, 1.2.3.4", "X-Cops-Front": "s"}), "s"), "1.2.3.4")
        self.assertEqual(t("::1", H({"X-Cops-Front": "s"}), "s"), "::1")

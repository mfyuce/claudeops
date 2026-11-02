"""web_hosts: bağlantı ANINDA gerçek karşı IP denetimi (DNS rebinding; P3 #36). Ağ yok: soket sahte."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import hosts  # noqa: E402
from claudeops.commands import web_hosts  # noqa: E402


class FakeSock:
    def __init__(self, ip):
        self.ip = ip

    def getpeername(self):
        return (self.ip, 80)

    def close(self):
        pass


def connect_to(host, ip):
    conn = web_hosts._GuardedHTTPConnection(host, 80, timeout=1)

    def fake_connect(self):
        self.sock = FakeSock(ip)
    with mock.patch.object(web_hosts.http.client.HTTPConnection, "connect", fake_connect):
        conn.connect()
    return conn


class PeerGuardTest(unittest.TestCase):
    def test_dns_name_resolving_to_loopback_is_refused(self):
        for ip in ("127.0.0.1", "169.254.169.254", "::ffff:169.254.169.254", "0.0.0.0", "::1"):
            with self.assertRaises(OSError, msg=ip):
                connect_to("rebind.example.com", ip)

    def test_dns_name_resolving_to_lan_is_allowed(self):
        connect_to("box.lan.example", "192.168.1.20")

    def test_ip_literal_is_not_rechecked(self):
        connect_to("127.0.0.1", "127.0.0.1")    # literal: kayıt anında denetlenir (test sunucuları vb.)

    def test_helpers(self):
        self.assertTrue(hosts.ip_is_blocked("fe80::1%eth0"))
        self.assertFalse(hosts.ip_is_blocked("10.0.0.5"))
        self.assertFalse(hosts.ip_is_blocked("garbage"))
        self.assertTrue(hosts.hostname_is_dns_name("a.example"))
        self.assertFalse(hosts.hostname_is_dns_name("10.0.0.5"))

    def test_conn_cls_for(self):
        self.assertTrue(issubclass(web_hosts._conn_cls_for("https"), web_hosts.http.client.HTTPSConnection))
        self.assertTrue(issubclass(web_hosts._conn_cls_for("http"), web_hosts.http.client.HTTPConnection))


if __name__ == "__main__":
    unittest.main()

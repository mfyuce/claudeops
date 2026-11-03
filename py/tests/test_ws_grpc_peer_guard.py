"""#36: ws_connect ve gRPC kanalı da bağlantı ANI IP denetiminden geçer. Ağ yok: soket/getaddrinfo sahte."""
import os
import socket
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_grpc, web_hosts  # noqa: E402


class FakeSock:
    def __init__(self, ip):
        self.ip = ip
        self.closed = False

    def getpeername(self):
        return (self.ip, 80)

    def close(self):
        self.closed = True


class WsGuardTest(unittest.TestCase):
    def test_dns_name_resolving_to_loopback_is_refused_and_socket_closed(self):
        s = FakeSock("127.0.0.1")
        with mock.patch.object(socket, "create_connection", return_value=s), \
                mock.patch.object(web_hosts, "ws_connect") as wc:
            with self.assertRaises(web_hosts._BlockedPeer):
                web_hosts._guarded_ws_connect("ws://evil.example/x")
        wc.assert_not_called()
        self.assertTrue(s.closed)

    def test_public_ip_passes_socket_to_ws_connect(self):
        s = FakeSock("93.184.216.34")
        with mock.patch.object(socket, "create_connection", return_value=s), \
                mock.patch.object(web_hosts, "ws_connect", return_value="conn") as wc:
            self.assertEqual(web_hosts._guarded_ws_connect("ws://ok.example/x"), "conn")
        self.assertIs(wc.call_args.kwargs["sock"], s)

    def test_ip_literal_skips_the_pre_connect(self):
        with mock.patch.object(socket, "create_connection") as cc, \
                mock.patch.object(web_hosts, "ws_connect", return_value="c"):
            web_hosts._guarded_ws_connect("ws://10.0.0.5:9/x")
        cc.assert_not_called()


class GrpcGuardTest(unittest.TestCase):
    def test_blocked_resolution_refused(self):
        info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]
        with mock.patch.object(socket, "getaddrinfo", return_value=info):
            with self.assertRaises(OSError):
                web_grpc._check_grpc_host("meta.example", 80)

    def test_unresolvable_is_fail_closed(self):
        with mock.patch.object(socket, "getaddrinfo", side_effect=socket.gaierror("x")):
            with self.assertRaises(OSError):
                web_grpc._check_grpc_host("nx.example", 80)

    def test_public_and_literal_pass(self):
        info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        with mock.patch.object(socket, "getaddrinfo", return_value=info):
            web_grpc._check_grpc_host("ok.example", 80)
        web_grpc._check_grpc_host("10.1.2.3", 80)


if __name__ == "__main__":
    unittest.main()

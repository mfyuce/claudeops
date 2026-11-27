"""gRPC keepalive uyumu: sunucu, istemcimizin ping sıklığını reddetmemeli (`too_many_pings`).

Süreler kısaltılır (istemci 100 ms'de bir ping); sunucu payı istemci sabitinden türediği için oran korunur. Ayrıca
istemcinin "verisiz iki ping'ten sonra 60 sn bekle" freni kapatılır: gerçek sürelerde GOAWAY o bekleyişlerle ~140-220 sn'de
gelir, burada ~3 sn'de.
Ağ: yalnız loopback, boş port.
"""
import os
import socket
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grpc  # noqa: E402

from claudeops.commands import web_grpc  # noqa: E402
from claudeops.proto import host_bridge_pb2 as pb2, host_bridge_pb2_grpc as pb2_grpc  # noqa: E402

TOKEN = "not-a-real-token"
FAST_MS = 100
WATCH_SECONDS = 6.0   # düzeltmesiz kopuş ~3 sn; payla


def _boom(*_a):
    raise RuntimeError("veri yok")       # akış açık kalır, hiç kare gelmez


class KeepAliveTest(unittest.TestCase):
    def setUp(self):
        fast = [(k, FAST_MS if k == "grpc.keepalive_time_ms" else v) for k, v in web_grpc._KEEPALIVE_OPTIONS]
        p = mock.patch.object(web_grpc, "_KEEPALIVE_OPTIONS", fast)
        p.start()
        self.addCleanup(p.stop)
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        fast.append(("grpc.http2.max_pings_without_data", 0))
        server = web_grpc.start_grpc_server(port, TOKEN, _boom, _boom)
        self.assertIsNotNone(server)
        self.addCleanup(lambda: server.stop(0).wait(5))
        self.channel = grpc.insecure_channel(f"127.0.0.1:{port}",
                                             options=fast + [("grpc.use_local_subchannel_pool", 1)])
        self.addCleanup(self.channel.close)
        self.stub = pb2_grpc.HostBridgeStub(self.channel)
        self.md = web_grpc._auth_metadata(TOKEN)

    def test_silent_stream_is_not_cut_for_pinging(self):
        call = self.stub.StreamStatus(pb2.StreamStatusRequest(), metadata=self.md)
        self.addCleanup(call.cancel)
        ended = threading.Event()
        call.add_callback(ended.set)
        self.assertFalse(ended.wait(WATCH_SECONDS), "akış sunucu tarafından kesildi")

    def test_idle_channel_keeps_its_connection(self):
        states = []
        self.stub.Ping(pb2.PingRequest(), metadata=self.md, timeout=5)
        self.channel.subscribe(states.append)
        self.addCleanup(self.channel.unsubscribe, states.append)
        time.sleep(WATCH_SECONDS)
        self.assertEqual(set(states), {grpc.ChannelConnectivity.READY}, states)


class KeepAliveValuesTest(unittest.TestCase):
    def test_server_allows_pings_more_often_than_the_client_sends_them(self):
        client = dict(web_grpc._KEEPALIVE_OPTIONS)
        server = dict(web_grpc._server_options())
        self.assertLess(server["grpc.http2.min_ping_interval_without_data_ms"], client["grpc.keepalive_time_ms"])
        self.assertEqual(server["grpc.keepalive_permit_without_calls"], client["grpc.keepalive_permit_without_calls"])


if __name__ == "__main__":
    unittest.main()

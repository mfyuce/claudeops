"""TBD#392: "yalnız imzalı istek" kipinde gRPC terminal akışı reddedilir, istemci WebSocket'e düşer.

Gerçek gRPC sunucusu ve gerçek WebSocket sunucusu (loopback); yalnız host kaydı ve kademe sahte."""
import json
import os
import socket
import sys
import threading
import time
import unittest
from unittest import mock

import grpc
from websockets.sync.server import serve as ws_serve

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import authz, extensions  # noqa: E402
from claudeops.commands import web_grpc, web_hosts  # noqa: E402

TOKEN = "t0k"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(fn, pred, timeout=8.0):
    end = time.monotonic() + timeout
    while True:
        v = fn()
        if pred(v):
            return v
        if time.monotonic() >= end:
            raise AssertionError(f"timeout; last = {v!r}")
        time.sleep(0.02)


class _GrpcBase(unittest.TestCase):
    def setUp(self):
        authz.reset()
        self.addCleanup(authz.reset)
        self.term_calls = []

        def term(name, lang):
            self.term_calls.append(name)
            return {"ok": True, "text": f"{name}#grpc{len(self.term_calls)}", "masked": False, "mode": ""}

        port = _free_port()
        self.server = web_grpc.start_grpc_server(port, TOKEN, lambda: {"sessions": []}, term)
        self.assertIsNotNone(self.server)
        self.addCleanup(lambda: self.server.stop(0).wait(5))
        self.url = f"http://127.0.0.1:{port}"
        self.addCleanup(self._drop_channel)

    def _drop_channel(self):
        with web_grpc._channel_lock:
            ch = web_grpc._channels.pop(self.url, None)
        if ch is not None:
            ch.close()

    def term_stream(self):
        call = web_grpc.open_term_stream(self.url, TOKEN, "s1", "en")
        self.addCleanup(call.cancel)
        return call

    def assertRefused(self, call):
        with self.assertRaises(grpc.RpcError) as cm:
            next(call)
        self.assertEqual(cm.exception.code(), grpc.StatusCode.PERMISSION_DENIED)


class ServerGateTest(_GrpcBase):
    def test_without_hook_stream_serves_as_before(self):
        self.assertEqual(next(self.term_stream()).text, "s1#grpc1")

    def test_closed_gate_refuses_before_reading_the_terminal(self):
        authz.set_grpc_term_gate(lambda: False)
        self.assertRefused(self.term_stream())
        self.assertEqual(self.term_calls, [])

    def test_raising_or_non_true_gate_is_refused(self):
        def boom():
            raise RuntimeError("x")

        for gate in (boom, lambda: None, lambda: "yes"):
            authz.set_grpc_term_gate(gate)
            self.assertRefused(self.term_stream())
        self.assertEqual(self.term_calls, [])

    def test_open_stream_is_cut_when_gate_closes(self):
        allowed = [True]
        authz.set_grpc_term_gate(lambda: allowed[0])
        call = self.term_stream()
        next(call)
        allowed[0] = False
        with self.assertRaises(grpc.RpcError) as cm:
            for _ in range(200):
                next(call)
        self.assertEqual(cm.exception.code(), grpc.StatusCode.PERMISSION_DENIED)
        n = len(self.term_calls)
        time.sleep(0.5)
        self.assertEqual(len(self.term_calls), n)

    def test_ping_and_status_stream_are_not_gated(self):
        authz.set_grpc_term_gate(lambda: False)
        self.assertTrue(web_grpc.probe(self.url, TOKEN, timeout=3.0))
        call = web_grpc.open_status_stream(self.url, TOKEN)
        self.addCleanup(call.cancel)
        self.assertTrue(next(call).ok)

    def test_extension_api_registers_the_gate_and_reset_clears_it(self):
        extensions.ExtensionAPI.set_grpc_term_gate(mock.Mock(), lambda: False)
        self.assertFalse(authz.grpc_term_allowed())
        authz.reset()
        self.assertTrue(authz.grpc_term_allowed())


class ClientFallbackTest(_GrpcBase):
    def setUp(self):
        super().setUp()
        self.ws_paths = []

        def handler(conn):
            self.ws_paths.append(conn.request.path)
            try:
                while True:
                    conn.send(json.dumps({"type": "term", "data": {"ok": True, "text": "s1#ws"}}))
                    time.sleep(0.05)
            except Exception:
                pass

        self.ws = ws_serve(handler, "127.0.0.1", 0)
        threading.Thread(target=self.ws.serve_forever, daemon=True).start()
        self.addCleanup(self.ws.shutdown)
        host = {"name": "h1", "base_url": f"http://127.0.0.1:{self.ws.socket.getsockname()[1]}",
                "grpc_url": self.url, "token": TOKEN}
        self.host = host
        for p in (mock.patch.object(web_hosts.hosts_mod, "get_host", lambda n: host if n == "h1" else None),
                  mock.patch.object(web_hosts, "get_tier", lambda n: "grpc"),
                  mock.patch.object(web_hosts, "diag_log", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        self._clear()
        self.addCleanup(self._clear)

    def _clear(self):
        with web_hosts._term_relay_lock:
            relays = list(web_hosts._term_relays.values())
            web_hosts._term_relays.clear()
            getattr(web_hosts, "_grpc_term_refused", {}).clear()
        for r in relays:
            r.stop()

    def test_refused_grpc_term_stream_falls_back_to_websocket(self):
        authz.set_grpc_term_gate(lambda: False)
        fetch = web_hosts.term_output_relay("h1", "s1", "en")
        got = _wait(fetch, lambda v: v.get("ok"))
        self.assertEqual(got["text"], "s1#ws")
        self.assertTrue(self.ws_paths[0].startswith("/ws/term?"))
        self.assertEqual(self.term_calls, [])

    def test_other_session_goes_straight_to_websocket_then_grpc_is_retried_after_ttl(self):
        allowed = [False]
        authz.set_grpc_term_gate(lambda: allowed[0])
        _wait(web_hosts.term_output_relay("h1", "s1", "en"), lambda v: v.get("ok"))
        with mock.patch.object(web_grpc, "open_term_stream", side_effect=AssertionError("grpc")) as op:
            _wait(web_hosts.term_output_relay("h1", "s2", "en"), lambda v: v.get("ok"))
        op.assert_not_called()
        allowed[0] = True
        later = time.monotonic() + web_hosts._GRPC_TERM_REFUSED_TTL_SECONDS + 1
        with web_hosts._term_relay_lock:
            for k, until in web_hosts._grpc_term_refused.items():
                self.assertLess(until, later)
                web_hosts._grpc_term_refused[k] = time.monotonic() - 1
        got = _wait(web_hosts.term_output_relay("h1", "s3", "en"), lambda v: v.get("ok"))
        self.assertTrue(got["text"].startswith("s3#grpc"), got)

    def test_refusal_is_remembered_for_the_refusing_address_only(self):
        authz.set_grpc_term_gate(lambda: False)
        fetch = web_hosts.term_output_relay("h1", "s1", "en")
        fetch()
        relay = web_hosts._term_relays[("h1", "s1", "en", False)]
        self.assertTrue(_wait(lambda: {"ok": not relay.is_alive()}, lambda v: v["ok"])["ok"])
        old_url = self.host["grpc_url"]
        self.host["grpc_url"] = old_url.replace("127.0.0.1", "localhost")   # kayıt düzenlendi: yeni adres
        with mock.patch.object(web_grpc, "open_term_stream", side_effect=RuntimeError("x")) as op:
            fetch()
            _wait(lambda: {"ok": op.called}, lambda v: v["ok"])
        self.assertEqual(op.call_args[0][0], self.host["grpc_url"])          # yeni adres gRPC'den denenir
        self.assertEqual(list(web_hosts._grpc_term_refused), [("h1", old_url)])

    def test_other_grpc_failure_does_not_move_to_websocket(self):
        self.server.stop(0).wait(5)
        fetch = web_hosts.term_output_relay("h1", "s1", "en")
        end = time.monotonic() + 3.0
        while time.monotonic() < end:
            self.assertFalse(fetch().get("ok"))
            time.sleep(0.05)
        self.assertEqual(self.ws_paths, [])


if __name__ == "__main__":
    unittest.main()

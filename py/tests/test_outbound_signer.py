"""authz.set_outbound_signer: giden uzak-host isteklerine imza başlığı (docs/SIGNED-IDENTITY-FORWARDING.md faz 1)."""
import http.server
import threading
import unittest
from unittest import mock

from claudeops import authz, hosts as hosts_mod
from claudeops.commands import web_hosts

SEEN = []


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN.append(dict(self.headers))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *a):
        pass


class _ServerBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        SEEN.clear()
        authz.reset()
        authz.bind_principal(None)    # başka testlerden sızan kimlik olmasın
        self.p = mock.patch.object(hosts_mod, "load_hosts", return_value=[{"name": "u1", "base_url": self.base, "token": "t"}])
        self.p.start()

    def tearDown(self):
        self.p.stop()
        authz.bind_principal(None)
        authz.reset()



class OutboundSignerTest(_ServerBase):
    def _get(self):
        return web_hosts._http_json("GET", f"{self.base}/api/files/list?token=t", None, 5)

    def test_no_signer_no_header(self):
        authz.bind_principal(authz.Principal(uid="ali"))
        self.assertEqual(self._get()[0], 200)
        self.assertNotIn("X-Cops-Fwd", SEEN[-1])

    def test_signer_gets_host_path_and_header_sent_each_call(self):
        calls = []

        def signer(p, host, method, path, body):
            calls.append((p.uid, host, method, path, body))
            return {"X-Cops-Fwd": f"n{len(calls)}"}
        authz.set_outbound_signer(signer)
        authz.bind_principal(authz.Principal(uid="ali"))
        self._get()
        self._get()
        self.assertEqual(calls[0], ("ali", "u1", "GET", "/api/files/list", None))
        self.assertEqual([s["X-Cops-Fwd"] for s in SEEN], ["n1", "n2"])    # her istekte taze imza

    def test_no_principal_no_signing(self):
        authz.set_outbound_signer(lambda *a: {"X-Cops-Fwd": "x"})
        self._get()
        self.assertNotIn("X-Cops-Fwd", SEEN[-1])

    def test_refused_returns_error_without_request(self):
        def signer(*a):
            raise authz.OutboundRefused("no_key")
        authz.set_outbound_signer(signer)
        authz.bind_principal(authz.Principal(uid="ali"))
        status, body, err = self._get()
        self.assertEqual((status, body), (0, None))
        self.assertIn("outbound refused: no_key", err)
        self.assertEqual(SEEN, [])

    def test_signer_crash_falls_back_unsigned(self):
        def signer(*a):
            raise RuntimeError("boom")
        authz.set_outbound_signer(signer)
        authz.bind_principal(authz.Principal(uid="ali"))
        self.assertEqual(self._get()[0], 200)
        self.assertNotIn("X-Cops-Fwd", SEEN[-1])


if __name__ == "__main__":
    unittest.main()


class StatusExtraTest(unittest.TestCase):
    def tearDown(self):
        authz.reset()

    def test_extras(self):
        authz.set_status_extra("fwd", lambda: {"api": 1})
        authz.set_status_extra("none", lambda: None)

        def boom():
            raise RuntimeError("x")
        authz.set_status_extra("bad", boom)
        self.assertEqual(authz.status_extras(), {"fwd": {"api": 1}})
        authz.set_status_extra("fwd", None)
        self.assertEqual(authz.status_extras(), {})


class PeekBodyTest(unittest.TestCase):
    """_Handler._peek_body/_read_body: gövde bir kez okunur, handler'a aynen kalır; keep-alive'da sızmaz."""

    def _h(self, body: bytes, line=object()):
        import io
        from claudeops.commands import web

        class H:
            pass
        h = H()
        h.headers = {"Content-Length": str(len(body))}
        h.rfile = io.BytesIO(body)
        h.raw_requestline = line
        import contextlib
        h._body_timeout_ctx = lambda: contextlib.nullcontext()
        for n in ("_peek_body", "_read_body", "_read_body_raw"):
            setattr(h, n, getattr(web._Handler, n).__get__(h))
        h._PEEK_BODY_MAX = web._Handler._PEEK_BODY_MAX
        return h

    def test_peek_then_read_same_bytes(self):
        h = self._h(b'{"a":1}')
        self.assertEqual(h._peek_body(), b'{"a":1}')
        self.assertEqual(h._peek_body(), b'{"a":1}')          # tekrar: önbellekten
        self.assertEqual(h._read_body(7), b'{"a":1}')           # handler aynı gövdeyi görür (soket tüketilmişti)

    def test_cache_not_leaked_to_next_request(self):
        h = self._h(b"abc")
        h._peek_body()
        h.raw_requestline = object()                             # keep-alive: yeni istek
        import io
        h.rfile = io.BytesIO(b"xyz")
        self.assertEqual(h._read_body(3), b"xyz")

    def test_too_large_returns_none(self):
        h = self._h(b"x")
        h.headers = {"Content-Length": str(h._PEEK_BODY_MAX + 1)}
        self.assertIsNone(h._peek_body())


class WsSignedKwTest(unittest.TestCase):
    def tearDown(self):
        authz.reset()

    def test_ws_kw(self):
        self.assertEqual(web_hosts._ws_signed_kw("u1", "/ws/term"), {})      # kanca yok: davranış aynı
        seen = []

        def signer(p, host, method, path, body):
            seen.append((p, host, method, path, body))
            return {"X-Cops-Fwd": "n"}
        authz.set_outbound_signer(signer)
        kw = web_hosts._ws_signed_kw("u1", "/ws/term")
        self.assertEqual(kw, {"additional_headers": {"X-Cops-Fwd": "n"}})
        self.assertEqual(seen[0][1:], ("u1", "GET", "/ws/term", None))
        self.assertIs(seen[0][0], authz.LEGACY)                              # panelin kendi kimliği

        def refuse(*a):
            raise authz.OutboundRefused("no_key")
        authz.set_outbound_signer(refuse)
        with self.assertRaises(authz.OutboundRefused):
            web_hosts._ws_signed_kw("u1", "/ws")


class Refused502Test(_ServerBase):
    """OutboundRefused (fwd_policy=strict) proxy katmanında 502 + net hata gövdesi; istek HİÇ gönderilmez."""

    def _refuse(self):
        def signer(*a):
            raise authz.OutboundRefused("remote_no_fwd")
        authz.set_outbound_signer(signer)
        authz.bind_principal(authz.Principal(uid="ali"))

    def test_proxy_get_and_action_502(self):
        self._refuse()
        with mock.patch.object(hosts_mod, "get_host", return_value={"name": "u1", "base_url": self.base, "token": "t"}):
            body, st = web_hosts.proxy_get("/api/files/list", "u1", {"p": "/"}, dedup=False)
            self.assertEqual(st, 502)
            self.assertEqual(body["reason"], "remote_no_fwd")
            self.assertFalse(body["ok"])
            body, st = web_hosts.proxy_action("/api/register", "u1", {"name": "x"})
            self.assertEqual(st, 502)
            rb, st, hd, err = web_hosts.proxy_get_raw("/api/files/download", "u1", {"p": "/x"})
            self.assertEqual(st, 502)
            self.assertIn("signed identity required", err)
        self.assertEqual(SEEN, [])

    def test_unreachable_stays_200(self):
        with mock.patch.object(hosts_mod, "get_host", return_value={"name": "u1", "base_url": "http://127.0.0.1:9", "token": "t"}):
            body, st = web_hosts.proxy_get("/api/files/list", "u1", {}, dedup=False)
        self.assertEqual(st, 200)
        self.assertIn("unreachable", body["error"])

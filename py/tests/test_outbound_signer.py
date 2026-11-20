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


class OutboundSignerTest(unittest.TestCase):
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

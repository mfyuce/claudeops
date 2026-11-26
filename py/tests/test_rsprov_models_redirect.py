"""TBD#389: ucli `/models` istekleri HTTP yönlendirmesini izlemez (API anahtarı başka adrese taşınmaz).

Yalnız 127.0.0.1 üzerinde iki sahte sunucu: biri 3xx döner, öteki gelen istekleri kaydeder.

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_models_redirect.py
"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_session_opts as uso  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402

BODY = json.dumps({"data": [{"id": "m", "task": "chat"}]}).encode()


class RedirectTest(unittest.TestCase):
    def _serve(self, handle):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                handle(self)

            def log_message(self, *a):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def setUp(self):
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.leaked = []
        self.status = 302

        def target(h):
            self.leaked.append(dict(h.headers))
            h.send_response(200)
            h.send_header("Content-Length", str(len(BODY)))
            h.end_headers()
            h.wfile.write(BODY)

        other = self._serve(target)

        def redirect(h):
            h.send_response(self.status)
            h.send_header("Location", other + "/v1/models")
            h.send_header("Content-Length", "0")
            h.end_headers()

        self.endpoint = self._serve(redirect) + "/v1"

    def test_evren_models_does_not_follow_redirects(self):
        for self.status in (301, 302, 303, 307, 308):
            with self.subTest(status=self.status), \
                    mock.patch.object(up, "byok_env_for", return_value={"UCLI_API_KEY": "gizli"}), \
                    mock.patch.object(up, "endpoint", return_value=self.endpoint), \
                    mock.patch.object(up, "_LIVE_CAPS", {}):
                self.assertIsNone(up._fetch_live_models())
                self.assertEqual(self.leaked, [])

    def test_service_models_does_not_follow_redirects(self):
        table = {"openai-x": ("openai-chat", self.endpoint, "K1"),
                 "anthropic-x": ("anthropic-messages", self.endpoint, "K2")}
        with mock.patch.object(uso, "services", return_value=table):
            for self.status in (301, 302, 303, 307, 308):
                for service in table:
                    with self.subTest(status=self.status, service=service), mock.patch.object(uso, "_MODELS_CACHE", {}):
                        self.assertEqual(uso.service_models(service, "gizli"), [])
                        self.assertEqual(self.leaked, [])


if __name__ == "__main__":
    unittest.main()

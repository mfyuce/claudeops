"""Eklenti yolu kancası (`register_route`) + panel yetkisi (`_ext_dispatch`): token YA DA oturum çerezi; çerez yalnız eklenti yollarını açar,
yazan istekte çerez tek başına yetmez; çekirdek yüzeyi önekleri reddedilir; eklenti hatası 500 (çekirdek düşmez). Canlı servis YOK."""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import extensions as ext  # noqa: E402
from claudeops import settings  # noqa: E402
from claudeops.commands import web  # noqa: E402

TOKEN = "ab12cd34"


class H:
    """_Handler'ın yalnız _ext_dispatch'in dokunduğu yüzeyi."""
    token = TOKEN

    def __init__(self, path, headers=None):
        self.path = path
        self.headers = headers or {}
        self.status = None
        self.sent = {}
        self.wfile = io.BytesIO()
        self.close_connection = False
        self.unauth = False

    def _authorized(self):
        return web._Handler._authorized(self)

    def _unauthorized(self):
        self.unauth = True

    def _json(self, obj, status=200):
        self.status = status

    def send_response(self, s):
        self.status = s

    def send_header(self, k, v):
        self.sent[k] = v

    def end_headers(self):
        pass

    def _read_body(self, n):
        return b""


def run(h, method="GET"):
    route = ext.match_route(method, h.path.split("?")[0])
    web._Handler._ext_dispatch(h, method, route)


class Routes(unittest.TestCase):
    def setUp(self):
        self.saved = list(ext._ROUTES)
        api = ext.ExtensionAPI()
        api.register_route("/zz/", lambda r: r.json({"ok": True, "m": r.method}), ("GET", "POST"))

    def tearDown(self):
        ext._ROUTES[:] = self.saved

    def test_invalid_prefixes(self):
        api = ext.ExtensionAPI()
        for bad in ("", "x/", "/", "/api/", "/api/x/", "/ws", "/v1/x", "/q/", "/assets/"):
            with self.assertRaises(ValueError, msg=bad):
                api.register_route(bad, lambda r: None)

    def test_match(self):
        self.assertIsNotNone(ext.match_route("GET", "/zz/a"))
        self.assertIsNotNone(ext.match_route("GET", "/zz"))
        self.assertIsNone(ext.match_route("DELETE", "/zz/a"))
        self.assertIsNone(ext.match_route("GET", "/other/"))

    def test_no_auth_is_401_and_wrong_cookie(self):
        h = H("/zz/a")
        run(h)
        self.assertTrue(h.unauth)
        h = H("/zz/a", {"Cookie": "cops_ext=deadbeef"})
        run(h)
        self.assertTrue(h.unauth)

    def test_token_sets_cookie_cookie_then_works(self):
        h = H(f"/zz/a?token={TOKEN}")
        run(h)
        self.assertEqual(h.status, 200)
        self.assertIn("HttpOnly", h.sent["Set-Cookie"])
        self.assertIn("SameSite=Strict", h.sent["Set-Cookie"])
        self.assertNotIn(TOKEN, h.sent["Set-Cookie"])          # token çereze girmez (HMAC)
        cookie = h.sent["Set-Cookie"].split(";")[0]
        h2 = H("/zz/b", {"Cookie": cookie})
        run(h2)
        self.assertEqual(h2.status, 200)
        self.assertFalse(h2.unauth)
        self.assertNotIn("Set-Cookie", h2.sent)

    def test_post_with_cookie_needs_header(self):
        cookie = f"cops_ext={ext.cookie_value(TOKEN)}"
        h = H("/zz/a", {"Cookie": cookie})
        run(h, "POST")
        self.assertEqual(h.status, 403)
        h = H("/zz/a", {"Cookie": cookie, "X-Cops-Ext": "1"})
        run(h, "POST")
        self.assertEqual(h.status, 200)

    def test_plugin_error_is_500(self):
        ext.ExtensionAPI().register_route("/boom/", lambda r: 1 / 0)
        h = H(f"/boom/?token={TOKEN}")
        run(h)
        self.assertEqual(h.status, 500)

    def test_cookie_does_not_open_core_api(self):
        h = H("/api/status", {"Cookie": f"cops_ext={ext.cookie_value(TOKEN)}"})
        self.assertFalse(h._authorized())

    def test_empty_token_never_matches(self):
        self.assertFalse(ext.cookie_ok("cops_ext=", ""))
        self.assertFalse(ext.cookie_ok("cops_ext=" + ext.cookie_value(""), ""))


class ReaderConfig(unittest.TestCase):
    def test_validation(self):
        import tempfile
        d = tempfile.mkdtemp()
        orig = settings.load_settings
        try:
            for raw, want in (({}, ""), ("x", ""), ({"dir": "/nonexistent"}, ""), ({"dir": d}, "")):
                settings.load_settings = lambda raw=raw: {"reader": raw}
                self.assertEqual(settings.reader_config()["dir"], want)
            open(os.path.join(d, "index.html"), "w").close()
            settings.load_settings = lambda: {"reader": {"dir": d}}
            self.assertEqual(settings.reader_config()["dir"], os.path.realpath(d))
        finally:
            settings.load_settings = orig


if __name__ == "__main__":
    unittest.main()

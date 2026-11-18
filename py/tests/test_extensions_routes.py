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

    def test_routes_listed_for_panel_tabs(self):
        self.assertIn("/zz/", ext.routes())      # /api/status `ext_routes` bunu taşır; panel eklenti sekmesi buna bakar

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

    def test_own_csp_flag_set_only_when_extension_sends_csp(self):
        ext.ExtensionAPI().register_route("/c1/", lambda r: r.send(200, b"x", "text/plain", {"Content-Security-Policy": "default-src 'none'"}))
        ext.ExtensionAPI().register_route("/c2/", lambda r: r.send(200, b"x", "text/plain"))
        h = H(f"/c1/?token={TOKEN}")
        run(h)
        self.assertTrue(h._ext_own_csp)
        h = H(f"/c2/?token={TOKEN}")
        run(h)
        self.assertFalse(h._ext_own_csp)

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


class LongestPrefix(unittest.TestCase):
    """Genel önek kayıt sırası yüzünden alt rotayı ezmez (review copsdev R-2, 15 Kas)."""

    def setUp(self):
        self.saved = list(ext._ROUTES)

    def tearDown(self):
        ext._ROUTES[:] = self.saved

    def test_longest_prefix_wins_regardless_of_order(self):
        ext._ROUTES[:] = [{"prefix": "/zz/", "fn": "genel", "methods": {"GET"}},
                          {"prefix": "/zz/admin/", "fn": "alt", "methods": {"GET"}}]
        self.assertEqual(ext.match_route("GET", "/zz/admin/x")["fn"], "alt")
        self.assertEqual(ext.match_route("GET", "/zz/other")["fn"], "genel")
        ext._ROUTES.reverse()
        self.assertEqual(ext.match_route("GET", "/zz/admin/x")["fn"], "alt")
        self.assertEqual(ext.match_route("GET", "/zz/admin")["fn"], "alt")     # önek.rstrip('/') eşleşmesi
        self.assertIsNone(ext.match_route("POST", "/zz/admin/x"))               # yöntem uymazsa eşleşmez


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


class ApiRoutes(unittest.TestCase):
    """K12 `register_api_route`: `/api/enterprise/...` kimlik + eylem kapısı + denetim; çerez KABUL EDİLMEZ; JSON olmayan POST 415."""
    def setUp(self):
        from claudeops import authz
        self.authz = authz
        self.saved = list(ext._ROUTES)
        authz.reset()
        self.seen = []
        ext.ExtensionAPI().register_api_route("/api/enterprise/admin/users/", lambda r: r.json({"ok": True, "p": r.principal.uid}),
                                              ("GET", "POST"), "admin.users")

    def tearDown(self):
        ext._ROUTES[:] = self.saved
        self.authz.reset()

    def _h(self, headers=None, path="/api/enterprise/admin/users/x"):
        h = H(path, headers or {})
        h.command = "GET"
        h._principal = lambda: web._Handler._principal(h)
        h._gate = lambda m, p, d=None: web._Handler._gate(h, m, p, d)
        h._request_view = lambda: None
        return h

    def test_register_validation(self):
        api = ext.ExtensionAPI()
        for pre, act in (("/api/x/", "admin.users"), ("/api/enterprise/a", "admin.users"), ("/api/enterprise/a/", "evil"),
                         ("/api/enterprise/a/", "status.read")):
            with self.assertRaises(ValueError):
                api.register_api_route(pre, lambda r: None, ("GET",), act)
        with self.assertRaises(ValueError):
            api.register_route("/api/enterprise/zz/", lambda r: None)       # eski kanca hâlâ /api/ reddeder

    def test_token_ok_and_principal(self):
        h = self._h({"Authorization": "Bearer " + TOKEN})
        h.__class__ = type("HH", (H,), {})        # _authorized gerçek mantık: Bearer
        run(h)
        self.assertEqual(h.status, 200)

    def test_no_token_401_and_cookie_not_accepted(self):
        h = self._h()
        run(h)
        self.assertTrue(h.unauth)
        h = self._h({"Cookie": f"{ext.COOKIE_NAME}={ext.cookie_value(TOKEN)}"})
        run(h)
        self.assertTrue(h.unauth)

    def test_post_requires_json(self):
        h = self._h({"Authorization": "Bearer " + TOKEN, "Content-Type": "application/x-www-form-urlencoded"})
        run(h, "POST")
        self.assertEqual(h.status, 415)

    def test_gate_uses_action_and_forbids(self):
        calls = []
        self.authz.set_authorizer(lambda p, a, r: calls.append(a) or False)
        h = self._h({"Authorization": "Bearer " + TOKEN})
        run(h)
        self.assertEqual(h.status, 403)
        self.assertEqual(calls, ["admin.users"])

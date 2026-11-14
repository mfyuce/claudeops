"""Kimlik/yetki kancaları (çekirdek, OSS): kanca YOKKEN davranış aynı; kanca VARKEN fail-closed, 401/403, süzgeç, denetim.
Gerçek HTTP (ThreadingHTTPServer + _Handler), canlı oturum/tmux/ağ YOK."""
import json
import os
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import authz, extensions  # noqa: E402
from claudeops.commands import web  # noqa: E402

PRE_AUTH = {"/assets/", "/favicon.svg", "/readfile/"}     # kimlik kapısından önce/ayrı yetkili (bilet, statik)


class DefaultsTest(unittest.TestCase):
    def setUp(self):
        authz.reset()

    tearDown = setUp

    def test_no_hooks_is_noop(self):
        self.assertFalse(authz.customized())
        self.assertTrue(authz.check(None, "x", authz.Resource()))
        payload = {"sessions": [1]}
        self.assertIs(authz.filter_status(authz.LEGACY, payload), payload)
        self.assertEqual(authz.LEGACY.roles, ("admin",))

    def test_every_web_path_has_an_action(self):
        src = open(os.path.join(os.path.dirname(web.__file__), "web.py"), encoding="utf-8").read()
        paths = set(re.findall(r'path == "(/[^"]+)"', src)) | set(re.findall(r'path\.startswith\("(/[^"]+)"\)', src))
        missing = sorted(p for p in paths if p not in PRE_AUTH and authz.action_for("GET", p) == authz.UNMAPPED)
        self.assertEqual(missing, [], "web.py'ye yeni uç eklendi: authz._ACTION_TABLE'a eylem adı ver")

    def test_unknown_path_unmapped(self):
        self.assertEqual(authz.action_for("POST", "/api/brand-new"), authz.UNMAPPED)
        self.assertEqual(authz.action_for("POST", "/api/term/input"), "term.write")
        self.assertEqual(authz.action_for("GET", "/"), "status.read")

    def test_fail_closed(self):
        authz.set_authenticator(lambda v: (_ for _ in ()).throw(RuntimeError("x")))
        with mock.patch.object(authz, "_log"):
            self.assertIsNone(authz.authenticate(authz.RequestView("GET", "/", {}, {}, {})))
        authz.set_authorizer(lambda p, a, r: (_ for _ in ()).throw(RuntimeError("x")))
        with mock.patch.object(authz, "_log"):
            self.assertFalse(authz.check(authz.LEGACY, "status.read", authz.Resource()))
        self.assertFalse(authz.check(None, "status.read", authz.Resource()))
        authz.set_status_filter(lambda p, d: 1 / 0)
        with mock.patch.object(authz, "_log"):
            self.assertEqual(authz.filter_status(authz.LEGACY, {"sessions": [1]}), {"sessions": []})

    def test_public_route_only_auth_prefix(self):
        with self.assertRaises(ValueError):
            extensions.ExtensionAPI().register_public_route("/api/other/", lambda r: None)


class HttpTest(unittest.TestCase):
    def setUp(self):
        authz.reset()
        p = mock.patch.object(web._Handler, "token", "tok")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(authz.reset)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, headers=None, body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                   data=json.dumps(body).encode() if body is not None else None, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_legacy_token_unchanged_without_hooks(self):
        self.assertEqual(self.call("GET", "/api/status", {"Authorization": "Bearer tok"})[0], 200)
        self.assertEqual(self.call("GET", "/api/status")[0], 401)

    def test_authenticator_replaces_token_and_401(self):
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)) if v.cookies.get("cops_t") == "good" else None)
        self.assertEqual(self.call("GET", "/api/status", {"Authorization": "Bearer tok"})[0], 401)   # web.token artık çözülmüyor
        self.assertEqual(self.call("GET", "/api/status", {"Cookie": "cops_t=good"})[0], 200)

    def test_authorizer_denies_403_and_audits(self):
        seen = []
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)))
        authz.set_authorizer(lambda p, a, r: a == "status.read")
        authz.add_audit_sink(lambda p, a, r, st: seen.append((p.uid, a, st)))
        self.assertEqual(self.call("GET", "/api/status", {"Cookie": "x=1"})[0], 200)
        code, body = self.call("POST", "/api/settings", {"Cookie": "x=1"}, {})
        self.assertEqual(code, 403)
        self.assertIn(("u1", "admin.config", 403), seen)
        self.assertIn(("u1", "status.read", 200), seen)

    def test_resource_from_body_name(self):
        res = []
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)))
        authz.set_authorizer(lambda p, a, r: (res.append(r) or r.name != "other"))
        code, _ = self.call("POST", "/api/term/input", {"Cookie": "x=1"}, {"name": "other", "text": "x"})
        self.assertEqual(code, 403)
        self.assertTrue(any(r.name == "other" and r.kind == "session" for r in res))

    def test_status_filter_applied(self):
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)))
        authz.set_status_filter(lambda p, d: {"sessions": [], "who": p.uid})
        code, body = self.call("GET", "/api/status", {"Cookie": "x=1"})
        self.assertEqual(json.loads(body).get("who"), "u1")


if __name__ == "__main__":
    unittest.main()

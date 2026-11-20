"""Rust ön kapı geçiş eki: gizli dosyası (0600), iç authz, ws-ticket/consume, uç koruması."""
import os, stat, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import authz, front, ws_ticket  # noqa: E402


class Secret(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        p = mock.patch.object(front.os.path, "expanduser", lambda x: x.replace("~", self.home)); p.start(); self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {}, clear=False); p.start(); self.addCleanup(p.stop)
        os.environ.pop("CLAUDEOPS_FRONT_SECRET", None)

    def test_ensure_creates_0600_and_is_stable(self):
        v = front.ensure_secret()
        self.assertEqual(len(v), 64)
        self.assertEqual(stat.S_IMODE(os.stat(front.secret_path()).st_mode), 0o600)
        self.assertEqual(front.ensure_secret(), v)
        self.assertEqual(front.read_secret(), v)

    def test_loose_permissions_are_not_trusted(self):
        front.ensure_secret()
        os.chmod(front.secret_path(), 0o644)
        self.assertEqual(front.read_secret(), "")

    def test_env_wins_and_missing_is_empty(self):
        self.assertEqual(front.read_secret(), "")
        os.environ["CLAUDEOPS_FRONT_SECRET"] = "e"
        self.assertEqual(front.read_secret(), "e")

    def test_trusted_front(self):
        self.assertTrue(front.trusted_front("127.0.0.1", {"X-Cops-Front": "s"}, "s"))
        self.assertFalse(front.trusted_front("10.0.0.2", {"X-Cops-Front": "s"}, "s"))
        self.assertFalse(front.trusted_front("127.0.0.1", {"X-Cops-Front": "x"}, "s"))
        self.assertFalse(front.trusted_front("127.0.0.1", {"X-Cops-Front": "s"}, ""))


class Authz(unittest.TestCase):
    def tearDown(self):
        authz.reset()

    def test_legacy_token_via_query_and_bearer(self):
        r = front.internal_authz({"method": "GET", "path": "/api/status", "query": {"token": "tok"}}, "tok")
        self.assertTrue(r["authenticated"]); self.assertEqual(r["principal"]["kind"], "legacy"); self.assertTrue(r["allowed"])
        r = front.internal_authz({"method": "GET", "path": "/api/status", "headers": {"Authorization": "Bearer tok"}}, "tok")
        self.assertTrue(r["authenticated"])
        r = front.internal_authz({"method": "GET", "path": "/api/status", "query": {"token": "no"}}, "tok")
        self.assertFalse(r["authenticated"]); self.assertNotIn("principal", r)

    def test_empty_token_fails_closed(self):
        r = front.internal_authz({"method": "GET", "path": "/api/status", "query": {"token": ""}}, "")
        self.assertFalse(r["authenticated"])

    def test_authenticator_and_authorizer_are_used(self):
        seen = {}
        def auth(view):
            seen["cookie"] = view.cookies.get("sid"); seen["ip"] = view.client_addr; seen["h"] = view.headers.get("Authorization")
            return authz.Principal(uid="u1", roles=("viewer",), kind="human") if view.cookies.get("sid") == "ok" else None
        authz.set_authenticator(auth)
        authz.set_authorizer(lambda p, action, res: action == "status.read" and res.name == "a")
        r = front.internal_authz({"method": "GET", "path": "/api/status", "headers": {"Cookie": "x=1; sid=ok", "Authorization": "Bearer z"},
                                  "client_ip": "1.2.3.4", "resource": {"kind": "session", "name": "a"}}, "tok")
        self.assertEqual((r["authenticated"], r["allowed"], r["action"]), (True, True, "status.read"))
        self.assertEqual((seen["cookie"], seen["ip"], seen["h"]), ("ok", "1.2.3.4", "Bearer z"))
        r = front.internal_authz({"method": "GET", "path": "/api/status", "headers": {"Cookie": "sid=ok"}, "resource": {"kind": "session", "name": "b"}}, "tok")
        self.assertFalse(r["allowed"])
        r = front.internal_authz({"method": "GET", "path": "/api/status", "headers": {"Cookie": "sid=bad"}}, "tok")
        self.assertFalse(r["authenticated"])

    def test_ws_ticket_fallback_for_ws_paths(self):
        authz.set_authenticator(lambda v: None)
        t = ws_ticket.issue(principal=authz.Principal(uid="u2", roles=("viewer",)))
        r = front.internal_authz({"method": "GET", "path": "/ws", "query": {"ticket": t}}, "")
        self.assertTrue(r["authenticated"]); self.assertEqual(r["principal"]["uid"], "u2")


class Ticket(unittest.TestCase):
    def test_consume_once_bound_and_unbound(self):
        t = ws_ticket.issue(principal=authz.Principal(uid="u3"))
        r = front.ws_ticket_consume({"ticket": t})
        self.assertEqual((r["valid"], r["principal"]["uid"]), (True, "u3"))
        self.assertFalse(front.ws_ticket_consume({"ticket": t})["valid"])          # tek kullanım
        t2 = ws_ticket.issue()
        r = front.ws_ticket_consume({"ticket": t2})
        self.assertEqual((r["valid"], r["principal"]), (True, None))
        self.assertFalse(front.ws_ticket_consume({"ticket": ""})["valid"])

    def test_expired(self):
        t = ws_ticket.issue(now=0.0)
        ok, p = ws_ticket.consume_full(t, now=ws_ticket.TTL_SECONDS + 1)
        self.assertFalse(ok)


class Wiring(unittest.TestCase):
    def test_internal_branch_guarded_before_auth(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claudeops", "commands", "web.py"), encoding="utf-8").read()
        i = src.index('if path.startswith("/api/_internal/"):')
        self.assertLess(i, src.index("agents_caller = self._agents_caller()", i - 2000))
        self.assertIn("front_mod.trusted_front(peer, self.headers)", src[i:i + 600])


if __name__ == "__main__":
    unittest.main()

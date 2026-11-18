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
            with urllib.request.urlopen(r, timeout=45) as resp:
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

    def test_agents_cookie_human_gated_on_get_and_post(self):
        """Çok kullanıcıda çerezli insan /api/agents/* için 401 değil, `agents.use` kapısından geçer (GET dalı genel kapıdan önce dönerdi)."""
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)) if v.cookies.get("cops_t") == "good" else None)
        seen = []
        authz.set_authorizer(lambda p, a, r: seen.append(a) or a != "agents.use")
        ck = {"Cookie": "cops_t=good"}
        self.assertEqual(self.call("GET", "/api/agents/models", ck)[0], 403)        # kapı soruldu ve reddetti
        self.assertEqual(self.call("POST", "/api/agents/start", ck, {})[0], 403)
        self.assertIn("agents.use", seen)
        self.assertEqual(self.call("GET", "/api/agents/models")[0], 401)           # kimliksiz hâlâ 401
        authz.set_authorizer(lambda p, a, r: True)
        code = self.call("GET", "/api/agents/models", ck)[0]
        self.assertNotEqual(code, 401)                                              # izin verilince kimlik doğrulaması geçer

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

    def test_post_gate_sees_body_resource_once(self):
        res = []
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)))
        authz.set_authorizer(lambda p, a, r: (res.append((a, r.kind, r.name)) or (r.kind == "session" and r.name == "mine")))
        code, _ = self.call("POST", "/api/term/input", {"Cookie": "x=1"}, {"name": "mine", "text": "x"})
        self.assertNotEqual(code, 403)                       # eski hata: gövde okunmadan 'global' kaynakla sorulup kendi oturumu bile reddediliyordu
        self.assertEqual(res, [("term.write", "session", "mine")])      # tek karar, doğru kaynakla
        res.clear()
        code, _ = self.call("POST", "/api/files/ticket", {"Cookie": "x=1"}, {"name": "mine", "path": "a"})
        self.assertNotEqual(code, 403)
        self.assertEqual(self.call("POST", "/api/files/ticket", {"Cookie": "x=1"}, {"name": "theirs", "path": "a"})[0], 403)

    def test_orch_get_names_query_denied_if_any_name_denied(self):
        res = []
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)))
        authz.set_authorizer(lambda p, a, r: (res.append((a, r.name)) or r.name != "theirs"))
        self.assertEqual(self.call("GET", "/api/session/facts?names=mine,theirs", {"Cookie": "x=1"})[0], 403)
        self.assertEqual(res, [("status.read", "mine"), ("status.read", "theirs")])

    def test_files_without_name_is_400_even_when_global_allowed(self):
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)))
        authz.set_authorizer(lambda p, a, r: r.kind == "global")           # kaynaksız istek geçer, ama dosyaya ulaşamaz
        h = {"Cookie": "x=1"}
        self.assertEqual(self.call("GET", "/api/files/read?path=/etc/passwd", h)[0], 400)
        self.assertEqual(self.call("GET", "/api/files/download?path=/etc/passwd", h)[0], 400)
        self.assertEqual(self.call("GET", "/api/files/list?path=/", h)[0], 400)
        self.assertEqual(self.call("POST", "/api/files/ticket", h, {"path": "/etc/passwd"})[0], 400)
        self.assertEqual(self.call("POST", "/api/files/write", h, {"path": "/tmp/x", "content": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/files/delete", h, {"path": "/tmp/x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/files/ticket", h, {"name": "  ", "path": "a"})[0], 400)

    def test_ws_handshake_filters_status_for_principal(self):
        try:
            from websockets.sync.client import connect
        except ImportError:
            self.skipTest("websockets kurulu değil")
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)) if v.cookies.get("cops_t") == "good" else None)
        authz.set_status_filter(lambda p, d: {"sessions": [s for s in d["sessions"] if s["name"] == "mine"]})
        payload = {"sessions": [{"name": "mine"}, {"name": "theirs"}]}
        url = f"ws://127.0.0.1:{self.port}/ws"
        with mock.patch.object(web, "_status_payload", lambda: payload):
            with connect(url, additional_headers={"Cookie": "cops_t=good"}, ping_interval=None, close_timeout=3) as c:
                msg = json.loads(c.recv(timeout=5))
            self.assertEqual(msg["data"], {"sessions": [{"name": "mine"}]})          # süzülmüş ilk push
            with self.assertRaises(Exception):                                       # kimliksiz: 401, yükseltme yok
                connect(url, ping_interval=None, close_timeout=3)
            authz.set_status_filter(None)
            with connect(url, additional_headers={"Cookie": "cops_t=good"}, ping_interval=None, close_timeout=3) as c:
                self.assertEqual(json.loads(c.recv(timeout=5))["data"], payload)    # süzgeç yoksa aynen

    def test_status_filter_applied(self):
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)))
        authz.set_status_filter(lambda p, d: {"sessions": [], "who": p.uid})
        code, body = self.call("GET", "/api/status", {"Cookie": "x=1"})
        self.assertEqual(json.loads(body).get("who"), "u1")

    def test_public_route_skips_auth_but_other_ext_routes_need_admin(self):
        extensions._ROUTES[:] = []
        self.addCleanup(lambda: extensions._ROUTES.__setitem__(slice(None), []))
        api = extensions.ExtensionAPI()
        api.register_public_route("/api/auth/", lambda r: r.json({"ok": True}))
        api.register_route("/zz/", lambda r: r.json({"zz": 1}))
        authz.set_authenticator(lambda v: {"u": authz.Principal("u1", ("user",)), "a": authz.Principal("a", ("admin",))}.get(v.cookies.get("c")))
        self.assertEqual(self.call("GET", "/api/auth/x")[0], 200)                      # kimliksiz
        self.assertEqual(self.call("GET", "/zz/")[0], 401)
        self.assertEqual(self.call("GET", "/zz/", {"Cookie": "c=u"})[0], 403)
        self.assertEqual(self.call("GET", "/zz/", {"Cookie": "c=a"})[0], 200)

    def test_ui_extension_list_and_files(self):
        import tempfile
        d = tempfile.mkdtemp()
        open(d + "/index.js", "w").write("x=1")
        extensions._UI_EXTS.clear()
        self.addCleanup(extensions._UI_EXTS.clear)
        extensions.ExtensionAPI().register_ui_extension("adm", d, roles=("admin",), title="Admin")
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)) if v.cookies.get("c") == "u" else authz.Principal("a", ("admin",)))
        h_user, h_admin = {"Cookie": "c=u"}, {"Cookie": "c=a"}
        self.assertEqual(json.loads(self.call("GET", "/api/ui/extensions", h_user)[1])["extensions"], [])
        lst = json.loads(self.call("GET", "/api/ui/extensions", h_admin)[1])["extensions"]
        self.assertEqual(lst[0]["id"], "adm")
        self.assertNotIn("assets_dir", lst[0])
        self.assertEqual(self.call("GET", "/api/ui/ext/adm/index.js", h_admin)[0], 200)
        self.assertEqual(self.call("GET", "/api/ui/ext/adm/index.js", h_user)[0], 404)
        self.assertEqual(self.call("GET", "/api/ui/ext/adm/../../etc/passwd", h_admin)[0], 404)

    def test_session_event_emitted_on_success(self):
        from types import SimpleNamespace as NS
        ev = []
        authz.add_event_sink(lambda e, h, n, p: ev.append((e, h, n, p.uid)))
        fake = NS(path="/api/retire?x=1", _cur_data={"name": "s1", "host": "h"}, _cur_principal=authz.Principal("u1", ("user",)),
                  _json=lambda *a, **k: None)
        with mock.patch.object(web.web_ws, "notify_status_changed"):
            web._Handler._json_notify(fake, {"ok": True})
            web._Handler._json_notify(fake, {"ok": False})      # başarısız mutasyon olay üretmez
        self.assertEqual(ev, [("retired", "h", "s1", "u1")])

    def test_new_chat_and_adopt_event_use_real_instance_name(self):
        """new-chat gövdesinde `name` yok (base var), adopt'ta `name` ESKİ addır: olay yanıttaki gerçek adla yayılır (review copsdev R-2)."""
        from types import SimpleNamespace as NS
        ev = []
        authz.add_event_sink(lambda e, h, n, p: ev.append((e, n)))
        pr = authz.Principal("u1", ("user",))
        with mock.patch.object(web.web_ws, "notify_status_changed"):
            web._Handler._json_notify(NS(path="/api/new-chat", _cur_data={"base": "proj"}, _cur_principal=pr, _json=lambda *a, **k: None),
                                      {"ok": True, "name": "proj20261118", "kind": "x"})
            web._Handler._json_notify(NS(path="/api/adopt", _cur_data={"name": "eski"}, _cur_principal=pr, _json=lambda *a, **k: None),
                                      {"ok": True, "kind": "x", "new_name": "yeni"})
            web._Handler._json_notify(NS(path="/api/register", _cur_data={"name": "p1"}, _cur_principal=pr, _json=lambda *a, **k: None),
                                      {"ok": True})
        self.assertEqual(ev, [("created", "proj20261118"), ("adopted", "yeni"), ("created", "p1")])

    def test_session_event_emitted_before_response(self):
        """Sahiplik olayı yanıttan ÖNCE: register yanıtını alan istemcinin hemen ardından gelen isteği sahibi tanımalı."""
        from types import SimpleNamespace as NS
        order = []
        authz.add_event_sink(lambda e, h, n, p: order.append("event"))
        fake = NS(path="/api/register", _cur_data={"name": "s1"}, _cur_principal=authz.Principal("u1", ("user",)),
                  _json=lambda *a, **k: order.append("response"))
        with mock.patch.object(web.web_ws, "notify_status_changed"):
            web._Handler._json_notify(fake, {"ok": True})
        self.assertEqual(order, ["event", "response"])


class SpawnHookTest(unittest.TestCase):
    def setUp(self):
        authz.reset()
        self.addCleanup(authz.reset)

    def test_no_hook_empty_and_threadlocal(self):
        self.assertEqual(authz.spawn_env("claude", "n", "/w"), {})
        p = authz.Principal("u", ("user",))
        authz.bind_principal(p)
        self.assertIs(authz.current_principal(), p)
        seen = []
        t = threading.Thread(target=lambda: seen.append(authz.current_principal()))
        t.start(); t.join()
        self.assertEqual(seen, [None])                               # başka iş parçacığına sızmaz
        authz.bind_principal(None)

    def test_hook_env_refusal_and_fail_closed(self):
        authz.set_spawn_hook(lambda p, cli, name, cwd: {"X_DIR": f"/d/{cli}"})
        self.assertEqual(authz.spawn_env("claude", "n", "/w"), {"X_DIR": "/d/claude"})
        authz.set_spawn_hook(lambda p, cli, name, cwd: (_ for _ in ()).throw(authz.SpawnRefused("login_required:claude", "x")))
        with self.assertRaises(authz.SpawnRefused) as cm:
            authz.spawn_env("claude", "n", "/w")
        self.assertEqual(cm.exception.reason, "login_required:claude")
        self.assertIsInstance(cm.exception, ValueError)              # web.py'deki mevcut ValueError reddi yolundan geçer
        authz.set_spawn_hook(lambda *a: 1 / 0)
        with mock.patch.object(authz, "_log"), self.assertRaises(authz.SpawnRefused) as cm:
            authz.spawn_env("claude", "n", "/w")
        self.assertEqual(cm.exception.reason, "hook_error")

    def test_spawn_session_dry_run_gets_env(self):
        from claudeops import spawn
        authz.set_spawn_hook(lambda p, cli, name, cwd: {"CLAUDE_CONFIG_DIR": "/u/ali/claude"})
        with mock.patch.object(spawn, "detect_display", lambda: ":0"):
            out = spawn.spawn_session("nm", "/w", "m", dry_run=True, cli="shell", force_new=True)
        self.assertIn("CLAUDE_CONFIG_DIR=/u/ali/claude", out)
        authz.set_spawn_hook(lambda *a: (_ for _ in ()).throw(authz.SpawnRefused("login_required:claude")))
        with mock.patch.object(spawn, "detect_display", lambda: ":0"), self.assertRaises(ValueError):
            spawn.spawn_session("nm", "/w", "m", dry_run=True, cli="shell", force_new=True)

    def test_hook_session_usd_cap_min_with_default_and_popped_from_env(self):
        from claudeops import spawn

        class Prov:
            accepts_cli_opts = True
        with mock.patch("claudeops.ucli_session_opts.default_max_session_usd", return_value=8.0):
            env = {"CLAUDEOPS_SESSION_USD_CAP": "2.5", "KEEP": "1"}
            o = spawn._apply_hook_session_cap(env, None, Prov())
            self.assertEqual(o, {"max_session_usd": 2.5})            # kalan 2.5 < varsayılan 8
            self.assertEqual(env, {"KEEP": "1"})                      # oturuma sızmaz
            self.assertEqual(spawn._apply_hook_session_cap({"CLAUDEOPS_SESSION_USD_CAP": "50"}, None, Prov()), {"max_session_usd": 8.0})
            self.assertEqual(spawn._apply_hook_session_cap({"CLAUDEOPS_SESSION_USD_CAP": "3"}, {"max_session_usd": 1}, Prov()), {"max_session_usd": 1.0})
            self.assertEqual(spawn._apply_hook_session_cap({"CLAUDEOPS_SESSION_USD_CAP": "0.001"}, None, Prov()), {"max_session_usd": 0.01})   # taban
            for bad in ("0", "x", "-1", "inf", ""):
                self.assertIsNone(spawn._apply_hook_session_cap({"CLAUDEOPS_SESSION_USD_CAP": bad}, None, Prov()))
        with mock.patch("claudeops.ucli_session_opts.default_max_session_usd", return_value=0.0):           # ayar 0 = tavan yok: kanca tavanı yine uygulanır
            self.assertEqual(spawn._apply_hook_session_cap({"CLAUDEOPS_SESSION_USD_CAP": "4"}, None, Prov()), {"max_session_usd": 4.0})
        e2 = {"CLAUDEOPS_SESSION_USD_CAP": "2"}
        self.assertIsNone(spawn._apply_hook_session_cap(e2, None, object()))      # cap kabul etmeyen provider: opts değişmez, anahtar yine ayıklanır
        self.assertEqual(e2, {})

    def test_refusal_formatting(self):
        from claudeops import ucli_cost
        r = ucli_cost.refusal(authz.SpawnRefused("login_required:codex", "cmd"))
        self.assertEqual((r["ok"], r["code"], r["reason"]), (False, "spawn_refused", "login_required:codex"))


class TicketAndQuestionTest(HttpTest):
    def test_ws_ticket_bound_to_principal(self):
        from claudeops import ws_ticket
        p = authz.Principal("u1", ("user",))
        t = ws_ticket.issue(principal=p)
        self.assertIs(ws_ticket.consume_principal(t), p)
        self.assertIsNone(ws_ticket.consume_principal(t))              # tek kullanım
        t2 = ws_ticket.issue()
        self.assertIsNone(ws_ticket.consume_principal(t2))             # kimliksiz bilet kimlik vermez
        self.assertFalse(ws_ticket.consume(t2))

    def test_ticket_replaces_cookie_for_ws_only(self):
        seen = []
        authz.set_authenticator(lambda v: authz.Principal("u1", ("user",)) if v.cookies.get("c") == "1" else None)
        authz.set_authorizer(lambda p, a, r: (seen.append((p.uid, a)) or True))
        code, body, = self.call("POST", "/api/ws-ticket", {"Cookie": "c=1"}, {})
        ticket = json.loads(body)["ticket"]
        code, _ = self.call("GET", f"/ws/term?ticket={ticket}&name=x")           # çerezsiz: bilet kimliği taşır (WS yükseltmesi yok -> 4xx ama 401 DEĞİL)
        self.assertNotEqual(code, 401)
        self.assertIn(("u1", "term.read"), seen)
        code, _ = self.call("GET", f"/ws/term?ticket={ticket}&name=x")           # ikinci kullanım: kimlik yok
        self.assertEqual(code, 401)
        t3 = json.loads(self.call("POST", "/api/ws-ticket", {"Cookie": "c=1"}, {})[1])["ticket"]
        self.assertEqual(self.call("GET", f"/api/status?ticket={t3}")[0], 401)   # bilet yalnız /ws yollarında geçerli

    def test_steward_resource_uses_sid_not_project_name(self):
        r = authz.resources_from("/api/steward/answer", {}, {"name": "projA", "steward": "ayse"})
        self.assertEqual([(x.kind, x.steward, x.name) for x in r], [("steward", "ayse", "")])
        self.assertEqual(authz.resources_from("/api/steward/x", {"steward": ["bo"]}, None)[0].steward, "bo")
        self.assertEqual(authz.resources_from("/api/steward/x", {}, {})[0].steward, "default")

    def test_question_page_access_check(self):
        from types import SimpleNamespace as NS
        from claudeops.commands import web_steward as ws
        q = NS(id="q1", key="K", project="projA", status="open")
        calls = []
        with mock.patch.object(ws, "_find_question_any", return_value=("ayse", q)), \
                mock.patch.object(ws, "steward_config", return_value=NS(lang="tr")), \
                mock.patch.object(ws.sw, "question_page_html", lambda *a, **k: "HTML:" + (a[2] if len(a) > 2 else "")):
            self.assertEqual(ws.http_question_page("q1", "", False, None, "", access_check=lambda pr, sid: calls.append((pr, sid)) or True)[0], 200)
            self.assertEqual(calls, [("projA", "ayse")])
            self.assertEqual(ws.http_question_page("q1", "", False, None, "", access_check=lambda pr, sid: False)[0], 401)
            self.assertEqual(ws.http_question_page("q1", "", False, None, "", access_check=lambda pr, sid: 1 / 0)[0], 401)     # fail closed
            self.assertEqual(ws.http_question_page("q1", "K", False, None, "", access_check=lambda pr, sid: False)[0], 200)    # ?k= yolu aynen
            self.assertEqual(ws.http_question_page("q1", "", False, None, "")[0], 401)                                        # kanca yok: eski davranış


class ResourcesTest(unittest.TestCase):
    def test_multi_resources(self):
        r = authz.resources_from("/api/orch/start", {}, {"participants": [{"host": "h", "name": "a"}, {"name": "b"}, "x"]})
        self.assertEqual([(x.host, x.name) for x in r], [("h", "a"), ("", "b")])
        r = authz.resources_from("/v1/chat/completions", {}, {"model": "m1"})
        self.assertEqual(r[0].name, "m1")
        self.assertEqual(authz.resources_from("/api/files/list", {"name": ["q"]}, None)[0].name, "q")
        self.assertEqual(authz.resources_from("/api/settings", {}, {})[0].kind, "global")

    def test_names_query_and_body_each_a_resource(self):
        r = authz.resources_from("/api/session/facts", {"names": ["a, b,,c", "d"], "host": ["h"]}, None)
        self.assertEqual([(x.kind, x.host, x.name) for x in r], [("session", "h", n) for n in "abcd"])
        r = authz.resources_from("/api/orch/status", {"names": ["a,b"]}, {"names": ["b", "z"], "name": "a"})
        self.assertEqual([x.name for x in r], ["a", "b", "z"])                  # tekrarsız, hepsi ayrı
        self.assertEqual(authz.resources_from("/api/orch/status", {"names": [" , "]}, None)[0].kind, "global")

    def test_files_path_never_becomes_a_resource(self):
        # Mevcut durum belgesi: `path` kaynak üretmez; sahiplik YALNIZ `name`/`host` ile sınanır. `name` yoksa kaynak `global`,
        # ama tüm /api/files/* uçları name yoksa 400 (name_required) döner, dosyaya dokunmaz.
        r = authz.resources_from("/api/files/read", {"path": ["/etc/passwd"]}, None)
        self.assertEqual([(x.kind, x.name) for x in r], [("global", "")])
        r = authz.resources_from("/api/files/write", {}, {"path": "/etc/passwd", "content": "x", "name": "mine"})
        self.assertEqual([(x.kind, x.name) for x in r], [("session", "mine")])

    def test_event_sink_error_swallowed(self):
        authz.reset()
        authz._EVENT_SINKS.clear()
        authz.add_event_sink(lambda *a: 1 / 0)
        with mock.patch.object(authz, "_log"):
            authz.emit_event("/api/close", "", "n", None)
        authz._EVENT_SINKS.clear()

    def test_doc_prefix(self):
        from claudeops import statedocs
        statedocs.register_doc_prefix("auth/")
        self.addCleanup(statedocs._EXT_PREFIXES.clear)
        self.assertTrue(statedocs.db_ready("auth/users/u1"))
        self.assertFalse(statedocs.db_ready("other/x"))
        with self.assertRaises(ValueError):
            statedocs.register_doc_prefix("/etc/")

    def test_ws_client_view(self):
        from types import SimpleNamespace as NS
        from claudeops.commands import web_ws
        authz.reset()
        self.addCleanup(authz.reset)
        c = NS(handler=NS(_cur_principal=authz.Principal("u1", ("user",))))
        payload = {"sessions": [{"name": "a"}, {"name": "b"}]}
        self.assertIs(web_ws._client_view(c, payload), payload)
        authz.set_status_filter(lambda p, d: {"sessions": [s for s in d["sessions"] if s["name"] == "a"]})
        self.assertEqual(web_ws._client_view(c, payload), {"sessions": [{"name": "a"}]})
        self.assertEqual(web_ws._client_view(NS(handler=NS()), payload), {"sessions": []})     # principal yok = boş (fail closed)


if __name__ == "__main__":
    unittest.main()


class ExtensionCommandTest(unittest.TestCase):
    """K11: eklenti CLI komutu (`cops <ad> ...`); çekirdek adlarını ezemez, çekirdek komutu eklenti yüklemez."""
    def setUp(self):
        from claudeops import extensions
        self.ext = extensions
        extensions._COMMANDS.clear()
        self.addCleanup(extensions._COMMANDS.clear)

    def test_register_and_dispatch(self):
        from claudeops import cli
        got = []
        self.ext.ExtensionAPI().register_command("zent", lambda a: got.append(a) or 7, "x")
        with mock.patch.object(self.ext, "load"):
            args = cli.build_parser(["zent", "user", "list"]).parse_args(["zent", "user", "list", "--roles", "a"])
        self.assertEqual(args.func(args), 7)
        self.assertEqual(got, [["user", "list", "--roles", "a"]])

    def test_core_name_not_overridden_and_no_load_for_core(self):
        from claudeops import cli
        self.ext.ExtensionAPI().register_command("ls", lambda a: 99)
        with mock.patch.object(self.ext, "load") as ld:
            cli.build_parser(["ls"])
            ld.assert_not_called()
            p = cli.build_parser(["other"])
        self.assertNotEqual(p.parse_args(["ls"]).func.__name__, "<lambda>")

    def test_bad_name(self):
        with self.assertRaises(ValueError):
            self.ext.ExtensionAPI().register_command("-x", lambda a: 0)


class ExtActionTableTest(unittest.TestCase):
    def setUp(self):
        authz.reset()
        self.addCleanup(authz.reset)

    def test_action_for_reads_ext_table_longest_first(self):
        authz.register_action("/api/enterprise/admin/", "admin.users")
        authz.register_action("/api/enterprise/admin/sessions/", "admin.sessions")
        self.assertEqual(authz.action_for("GET", "/api/enterprise/admin/users/x"), "admin.users")
        self.assertEqual(authz.action_for("GET", "/api/enterprise/admin/sessions/owners"), "admin.sessions")
        self.assertIn("admin.sessions", authz.actions())
        self.assertNotIn("admin.sessions", authz.ACTIONS)
        authz.reset()
        self.assertEqual(authz.action_for("GET", "/api/enterprise/admin/users/x"), authz.UNMAPPED)

    def test_register_action_prefix_restricted(self):
        with self.assertRaises(ValueError):
            authz.register_action("/api/status", "admin.x")

    def test_ui_extension_title_en(self):
        import tempfile
        d = tempfile.mkdtemp()
        from claudeops import extensions
        extensions._UI_EXTS.clear()
        self.addCleanup(extensions._UI_EXTS.clear)
        extensions.ExtensionAPI().register_ui_extension("a1", d, title="Yönetim", title_en="Admin")
        extensions.ExtensionAPI().register_ui_extension("a2", d, title="Sadece")
        r = {e["id"]: e for e in extensions.ui_extensions()}
        self.assertEqual((r["a1"]["title_en"], r["a2"]["title_en"]), ("Admin", "Sadece"))

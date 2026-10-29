"""Uzak host'ta değnekçi A2 (TODO 2026-10-20 (14)): `GET /api/session/facts` (uzak taraf), `exact: true` (stop/handover/term
input yalnız tam ad), yerel istemcinin host yetenek önbelleği (404 -> api 0, 10 dk sonra yeniden yoklama, ağ hatasında
önbellek yazılmaz) ve facts ile zenginleşen uzak görünüm (`subagent_unknown=False`) / facts yoksa A1 yolu.

Gerçek ağ/uzak host/tmux/süreç öldürme/`spawn_session` YOK: `ws._remote` sahte, `web_hosts._http_json`/`_http_raw` AssertionError'a
bağlı, oturumlar sahte `Session`. Gerçek settings.json sha256'sı modül başında/sonunda karşılaştırılır.

Çalıştırma: python3 -m unittest discover -s py/tests"""
import hashlib
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_steward_remote import FakeHost, HOST, _Remote, _no_net, _row  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web, web_hosts as wh, web_steward as ws  # noqa: E402
from claudeops.session import Session  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None


def _sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def setUpModule():
    global _HASH_BEFORE
    _HASH_BEFORE = _sha(_REAL_SETTINGS)


def tearDownModule():
    if _sha(_REAL_SETTINGS) != _HASH_BEFORE:
        raise AssertionError("gerçek ~/.claude/claudeops/settings.json test sırasında değişti")


# ── uzak taraf: facts ucu ─────────────────────────────────────────────────────

class FakeProvider:
    def last_exchange(self, cwd, sid):
        return {"user": "u", "assistant": "A" * 25000}


class TestFactsEndpoint(unittest.TestCase):
    def setUp(self):
        self.live = [Session(name="oiso", pid=111, cwd="/srv/oiso", sid="s1", cli="claude"),
                     Session(name="oiso20261021", pid=222, cwd="/srv/o2", sid=None, cli="shell")]
        for p in (mock.patch.object(web, "find_sessions", lambda measure_cpu=False, **kw: list(self.live)),
                  mock.patch.object(web, "_process_started_at", lambda pid: time.time() - 120 if pid == 111 else None),
                  mock.patch.object(web, "get_provider", lambda cli: FakeProvider()),
                  mock.patch.object(web.web_steward, "context_tokens_for", lambda cwd, sid: 4321),
                  mock.patch.object(web.web_steward, "subagent_active_for", lambda cwd, sid: True)):
            p.start()
            self.addCleanup(p.stop)

    def test_facts_for_exact_names(self):
        r = web._session_facts(["oiso", "oiso", "yok"])
        self.assertEqual((r["ok"], r["api"]), (True, 1))
        self.assertEqual(r["capabilities"], ["exact_target", "session_facts"])
        f = r["sessions"]["oiso"]
        self.assertTrue(f["running"] and f["subagent_active"] and f["sid_known"])
        self.assertEqual(f["context_tokens"], 4321)
        self.assertAlmostEqual(f["started_age_s"], 120, delta=5)
        self.assertEqual(len(f["last_assistant"]), 20000)
        self.assertFalse(r["sessions"]["yok"]["running"])
        self.assertIsNone(r["sessions"]["yok"]["started_age_s"])

    def test_non_claude_has_no_context_or_subagent(self):
        f = web._session_facts(["oiso20261021"])["sessions"]["oiso20261021"]
        self.assertEqual((f["context_tokens"], f["subagent_active"], f["sid_known"], f["started_age_s"]),
                         (None, False, False, None))

    def test_no_names_gives_capabilities_only(self):
        r = web._session_facts([])
        self.assertEqual((r["sessions"], r["api"]), ({}, 1))

    def test_route_is_host_routed(self):
        self.assertIn("/api/session/facts", wh.GET_HOST_ROUTED_PATHS)


# ── uzak taraf: exact ─────────────────────────────────────────────────────────

class TestExact(unittest.TestCase):
    def setUp(self):
        # "cops" tam adı YOK; yalnız tarihli adaş canlı: eski davranış unique_base ile onu hedefler.
        self.live = [Session(name="cops20261021_1", pid=333, cwd="/srv/c", cli="claude")]
        self.killed = []
        self.sent = []
        import contextlib
        for p in (mock.patch.object(web, "find_sessions", lambda measure_cpu=False, **kw: list(self.live)),
                  mock.patch.object(web.inst_mod, "get_instance", lambda name: None),
                  mock.patch.object(web, "guard_lock", lambda timeout=None: contextlib.nullcontext()),
                  mock.patch.object(web, "kill_session_and_parent",
                                    lambda pid, grace=0, name="": self.killed.append(name) or {"ok": True}),
                  mock.patch.object(web, "is_tmux_backed", lambda pid: True),
                  mock.patch.object(web, "tmux_has_session", lambda name: True),
                  mock.patch.object(web, "tmux_send_keys", lambda name, text, settle_delay=0: self.sent.append(name) or True),
                  mock.patch.object(web.web_ws, "notify_term_activity", lambda name: None)):
            p.start()
            self.addCleanup(p.stop)

    def test_stop_exact_requires_full_name(self):
        self.assertEqual(web._stop("cops", exact=True), {"ok": False, "error": "no_exact_match"})
        self.assertEqual(self.killed, [])
        self.assertTrue(web._stop("cops20261021_1", exact=True)["ok"])
        self.assertEqual(self.killed, ["cops20261021_1"])

    def test_stop_without_exact_keeps_unique_base(self):
        self.assertTrue(web._stop("cops")["ok"])
        self.assertEqual(self.killed, ["cops20261021_1"])

    def test_term_input_exact(self):
        self.assertEqual(web._term_input("cops", "x", exact=True), {"ok": False, "error": "no_exact_match"})
        self.assertEqual(self.sent, [])
        self.assertEqual(web._term_input("cops20261021_1", "x", exact=True), {"ok": True})
        self.assertEqual(web._term_input("cops", "x"), {"ok": True})        # exact yok: eski davranış
        self.assertEqual(self.sent, ["cops20261021_1", "cops20261021_1"])

    def test_handover_exact_refuses_before_touching_session(self):
        with mock.patch.object(web, "apply_handover_downgrades", side_effect=AssertionError("dokunmamalı")):
            self.assertEqual(web._handover("cops", exact=True), {"ok": False, "error": "no_exact_match"})

    def test_term_resolve_exact(self):
        s, err = web._term_resolve("cops", exact=True)
        self.assertEqual((s, err), (None, {"ok": False, "error": "no_exact_match"}))
        s, err = web._term_resolve("cops")
        self.assertEqual((s.name, err), ("cops20261021_1", None))


# ── yerel istemci ─────────────────────────────────────────────────────────────

FACTS_CAPS = ["exact_target", "session_facts"]


class FactsHost(FakeHost):
    """FakeHost + `/api/session/facts`: `mode` = "new" (api 1), "old" (404), "down" (taşıma hatası), "plain" (api yok)."""

    def __init__(self):
        super().__init__()
        self.mode = "new"
        self.facts = {}

    def get(self, path, host, query, timeout=None):
        if path != "/api/session/facts":
            return super().get(path, host, query, timeout)
        self.gets.append((path, host, dict(query)))
        if self.mode == "old":
            return {"error": "not found"}, 404
        if self.mode == "down":
            return {"ok": False, "error": f"{host} unreachable: timeout"}, 200
        names = [n for n in query.get("names", "").split(",") if n]
        return {"ok": True, "api": 1, "capabilities": FACTS_CAPS,
                "sessions": {n: self.facts[n] for n in names if n in self.facts}}, 200


class TestClient(_Remote):
    def setUp(self):
        super().setUp()
        self.fake = FactsHost()
        p = mock.patch.object(ws, "_remote", self.fake)
        p.start()
        self.addCleanup(p.stop)
        sw.upsert_project("oiso", phase="planned", cadence_minutes=60, host=HOST)
        self.settings()

    def views(self):
        return [v for v in ws._collect_views(ws.steward_config()) if v.host == HOST]

    def facts_gets(self):
        return [g for g in self.fake.gets if g[0] == "/api/session/facts"]

    def test_404_caches_api0_and_rechecks_after_ten_minutes(self):
        self.fake.mode = "old"
        self.fake.set(HOST, [_row("oiso")])
        self.fake.chat[(HOST, "oiso")] = "metin"
        self.assertEqual(ws.host_capabilities(HOST), {"api": 0, "capabilities": []})
        self.assertEqual(len(self.facts_gets()), 1)
        v = self.views()[0]                                   # önbellek taze: yeniden yoklama YOK
        self.assertEqual(len(self.facts_gets()), 1)
        self.assertEqual((v.subagent_unknown, v.started_at, v.last_assistant), (True, 0.0, "metin"))   # A1 yolu
        t0 = ws._CAPS[HOST][0]
        ws._CAPS[HOST] = (t0 - ws.REMOTE_CAPS_RECHECK_SECONDS - 1, ws._CAPS[HOST][1])
        self.fake.mode = "new"                                # host yükseltildi
        self.assertEqual(ws.host_capabilities(HOST)["capabilities"], FACTS_CAPS)
        self.assertEqual(len(self.facts_gets()), 2)

    def test_404_is_not_a_transport_failure(self):
        self.fake.mode = "old"
        self.fake.set(HOST, [_row("oiso")])
        wh_before = dict(getattr(wh, "_last_ok_at", {}))
        ws.host_capabilities(HOST)
        self.assertEqual(dict(getattr(wh, "_last_ok_at", {})), wh_before)     # devre kesici/son başarı etkilenmez
        self.assertTrue(ws._host_fresh(ws._remote.status(HOST)))

    def test_network_error_does_not_write_cache(self):
        self.fake.mode = "down"
        self.assertEqual(ws.host_capabilities(HOST), {"api": 0, "capabilities": []})
        self.assertNotIn(HOST, ws._CAPS)
        self.fake.mode = "new"                                # hemen sonraki çağrı yeniden dener
        self.assertEqual(ws.host_capabilities(HOST)["api"], 1)
        self.fake.mode = "down"                               # sonra arıza: bilinen yetenek silinmez
        ws._CAPS[HOST] = (0.0, ws._CAPS[HOST][1])
        self.assertEqual(ws.host_capabilities(HOST, now=time.time())["capabilities"], FACTS_CAPS)

    def test_view_enriched_from_facts_single_request(self):
        self.fake.set(HOST, [_row("oiso", context={"tokens": 1000}, cache={"age": 30}),
                             _row("kapali", running=False)])
        self.fake.facts["oiso"] = {"running": True, "started_age_s": 600.0, "subagent_active": True,
                                   "context_tokens": 77000, "last_assistant": "STEWARD-ASK: hangi bölüm?",
                                   "sid_known": True}
        v = self.views()[0]
        self.assertEqual((v.subagent_unknown, v.subagent_active, v.context_tokens), (False, True, 77000))
        self.assertAlmostEqual(v.started_at, time.time() - 600, delta=5)
        self.assertEqual(v.last_assistant, "STEWARD-ASK: hangi bölüm?")
        self.assertEqual(self.facts_gets(), [("/api/session/facts", HOST, {"names": "oiso"})])   # host başına TEK istek
        self.assertEqual([g for g in self.fake.gets if g[0] == "/api/term/chat"], [])            # term/chat'e gerek yok
        self.assertEqual(self.fake.posts, [])

    def test_empty_facts_last_assistant_falls_back_to_term_chat_but_keeps_facts(self):
        # ulak_31 iggy (2026-10-29): facts last_assistant="" idi -> işaret taraması sessizce kapalıydı (DONE-CONFIRMED hiç görülmedi)
        self.fake.set(HOST, [_row("oiso", context={"tokens": 1000}, cache={"age": 30})])
        self.fake.facts["oiso"] = {"running": True, "started_age_s": 600.0, "subagent_active": False,
                                   "context_tokens": 77000, "last_assistant": "", "sid_known": True}
        self.fake.chat[(HOST, "oiso")] = "STEWARD-DONE-CONFIRMED: 3b7dd4b kalan açık iş 0, testler yeşil"
        v = self.views()[0]
        self.assertEqual(v.last_assistant, "STEWARD-DONE-CONFIRMED: 3b7dd4b kalan açık iş 0, testler yeşil")
        self.assertEqual((v.subagent_unknown, v.subagent_active, v.context_tokens), (False, False, 77000))   # olgular facts'ten
        self.fake.chat[(HOST, "oiso")] = ""                       # term/chat de boşsa: boş kalır, bozulmaz
        self.assertEqual(self.views()[0].last_assistant, "")

    def test_facts_missing_for_a_session_falls_back_to_term_chat(self):
        self.fake.set(HOST, [_row("oiso")])
        self.fake.chat[(HOST, "oiso")] = "yedek metin"         # host yeni ama bu ad için olgu yok
        v = self.views()[0]
        self.assertEqual((v.subagent_unknown, v.started_at, v.last_assistant), (True, 0.0, "yedek metin"))

    def test_old_host_keeps_a1_behavior(self):
        self.fake.mode = "old"
        self.fake.set(HOST, [_row("oiso", context={"tokens": 1234}, cache={"age": 20})])
        self.fake.chat[(HOST, "oiso")] = "selam"
        v = self.views()[0]
        self.assertEqual((v.context_tokens, v.started_at, v.subagent_unknown, v.last_assistant), (1234, 0.0, True, "selam"))

    def test_enriched_view_clears_subagent_unknown(self):
        # subagent_unknown=False + subagent_active=False: bilinmeyen-alt-ajan ertelemesi artık uygulanmaz.
        self.fake.set(HOST, [_row("oiso")])
        self.fake.facts["oiso"] = {"running": True, "started_age_s": 5.0, "subagent_active": False,
                                   "context_tokens": None, "last_assistant": "bitti"}
        v = self.views()[0]
        self.assertEqual((v.subagent_unknown, v.subagent_active), (False, False))


if __name__ == "__main__":
    unittest.main()

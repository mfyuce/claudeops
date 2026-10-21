"""Uzak host'taki projeyi yönetme, A1 (TODO 2026-10-20 (14)): `Project.host` + doğrulama/host değişimi kuralı, sahiplik
indeksinin `hosts` bölümü, `World.hosts/host_of/unavailable`, saf `select_rows`, uzak satırlardan görünüm (`_collect_views`
+ `_remote`), "host kapalı" tazelik kuralı, uzak oturumların slot sayımına girmesi, `_target`/`_apply`ta uzak hedefin
kapıları (A1'de koşulsuz red; A3'te `remote_actions` kapalıyken red, açıkken eylemler test_steward_remote_actions.py'de;
observe'da `would:` kaydı host alanıyla), uzak projede yerel dosya sistemi korumaları, CLI `set --host`.

Gerçek ağ/uzak host/tmux/servis/`spawn_session` YOK: `ws._remote` sahte host (`FakeHost`), `web_hosts._http_json`/`_http_raw`
ve `ws.spawn_session` AssertionError'a bağlı, `hosts.HOSTS_JSON` ve değnekçi dizini geçici (`_Tmp`). Gerçek settings.json
sha256'sı modül başında/sonunda karşılaştırılır.

Çalıştırma: python3 -m unittest discover -s py/tests"""
import contextlib
import dataclasses
import hashlib
import io
import json
import os
import sys
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import hosts, settings, steward as sw  # noqa: E402
from claudeops.commands import steward as cli, web_hosts as wh, web_steward as ws  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None
HOST = "ulak31"


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


def _no_net(*a, **k):
    raise AssertionError("test gerçek ağa çıkmaya çalıştı")


def _no_spawn(**kw):
    raise AssertionError("test gerçek oturum açmaya çalıştı: " + repr(kw.get("name")))


def _row(name, **kw):
    r = dict(name=name, running=True, cwd=f"/srv/{name}", cli="claude", busy=False, history_size=50, tmux=True,
             registered=True, instance=False, blueprint=name, model="claude-sonnet-5-5",
             context={"tokens": 1000}, cache={"age": 30})
    r.update(kw)
    return r


def _view(name, **kw):
    base = dict(running=True, cwd="/tmp/x", cli="claude", busy=False, history_size=100, tmux=True,
                started_at=1000.0, last_activity=1000.0)
    base.update(kw)
    return sw.SessionView(name=name, **base)


class FakeHost:
    """`ws._remote` yerine: host başına önbellek kaydı (`ok`, `sessions`, `closed`, `last_ok_at`), `term/chat` metinleri;
    `get`/`post` çağrıları kaydedilir. `post` A1'de HİÇ çağrılmamalı."""

    def __init__(self):
        self.hosts = {}
        self.chat = {}
        self.slow = {}
        self.gets = []
        self.posts = []

    def set(self, host, sessions=(), ok=True, age=1.0, closed=()):
        self.hosts[host] = {"ok": ok, "error": None if ok else "down", "sessions": [dict(r) for r in sessions],
                            "closed": [dict(r) for r in closed], "last_ok_at": time.time() - age if age is not None else 0.0}

    def status(self, host):
        st = self.hosts.get(host)
        return json.loads(json.dumps(st)) if st is not None else None

    def get(self, path, host, query, timeout=None):
        self.gets.append((path, host, dict(query)))
        if path == "/api/session/facts":      # A1 testleri eski host'u temsil eder: yeni uç yok (404)
            return {"error": "not found"}, 404
        delay = self.slow.get(query.get("name"))
        if delay:
            time.sleep(delay)
        return {"ok": True, "supported": True, "user": "", "assistant": self.chat.get((host, query.get("name")), "")}, 200

    def post(self, path, host, body, timeout=None):
        self.posts.append((path, host, dict(body)))
        raise AssertionError("A1: uzak eylem (proxy POST) çağrılmamalı")


class _Remote(_Tmp):
    """Bir kayıtlı uzak host (`ulak31`), sahte `_remote`, sahte oturum geri çağrıları; gerçek `_collect_views` koşar."""

    def setUp(self):
        super().setUp()
        d = self.dir.name
        hj = os.path.join(d, "hosts.json")
        with open(hj, "w", encoding="utf-8") as f:
            json.dump([{"name": HOST, "base_url": "http://127.0.0.1:9", "token": "t"},
                       {"name": "yuhem", "base_url": "http://127.0.0.1:9", "token": "t"}], f)
        ws._reset_contexts()
        ws._CAPS.clear()
        ws._HOST_HEALTH.clear()       # A3: süreç içi host sağlığı / red log tekrarsızlığı testler arası taşınmasın
        ws._DENIED_LOGGED.clear()
        ws._RECENT.clear()
        ws.invalidate_summary()
        self.addCleanup(ws._reset_contexts)
        self.fake = FakeHost()
        self.local_rows = []
        self.live = []
        self.fleet = {}
        self.calls = []
        self.touched = []

        def cb(kind):
            def f(name, *a, **kw):
                self.calls.append((kind, name))
                return {"ok": True}
            return f

        ws.configure(status_payload=lambda: {"sessions": [dict(r) for r in self.local_rows]},
                     fleet_status=lambda: dict(self.fleet), start=cb("start"), stop=cb("stop"),
                     handover=cb("handover"), register_project=cb("register"))
        patches = [
            mock.patch.object(hosts, "HOSTS_JSON", hj),
            mock.patch.object(ws, "_remote", self.fake),
            mock.patch.object(ws, "find_sessions", lambda measure_cpu=False, **kw: list(self.live)),
            mock.patch.object(ws, "find_stuck", lambda live: []),
            mock.patch.object(ws, "_running", lambda name: None),
            mock.patch.object(ws, "_ensure_running",
                              lambda name, **kw: self.touched.append(name) or {"ok": False, "error": "no tmux here"}),
            mock.patch.object(ws, "spawn_session", _no_spawn),
            mock.patch.object(wh, "_http_json", _no_net),
            mock.patch.object(wh, "_http_raw", _no_net),
            mock.patch.object(ws, "maybe_daily_summary", lambda cfg, now: None),
            mock.patch.object(ws, "_CARD_BACKGROUND", False),
            mock.patch.object(ws.inst_mod, "get_instance", lambda name: None),
            mock.patch.object(ws.web_ws, "notify_status_changed", lambda: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def settings(self, **kw):
        settings.save_settings({"steward": dict({"enabled": "on", "mode": "observe", "card_refresh": "off"}, **kw)})

    def log(self, event=None):
        return [e for e in sw.tail_log(500) if event is None or e.get("event") == event]


# ── saf çekirdek ─────────────────────────────────────────────────────────────

class TestSelectRows(unittest.TestCase):
    def world(self):
        idx = sw.build_ownership_index({"default": ["oiso", "loc"]}, services={"varaka": {}},
                                       hosts={"default": {"oiso": HOST}})
        return sw.world_for("default", idx)

    def names(self, rows, fresh=(HOST,)):
        return [(r.get("host", "local"), r["name"]) for r in sw.select_rows(rows, self.world(), fresh)]

    def test_remote_rows_only_for_their_projects_on_fresh_hosts(self):
        rows = [
            {"name": "loc", "host": "local"}, {"name": "adhoc"},                  # yerel: hep dahil
            {"name": "oiso", "host": "local"},                                    # uzak projenin YEREL adaşı: düşer
            {"name": "oiso20261021", "host": "local"},                            # tarihli yerel adaş da düşer
            {"name": "x_1", "host": "local", "instance": True, "blueprint": "oiso"},  # blueprint'i uzak proje: düşer
            {"name": "oiso", "host": HOST},                                       # uzak proje, doğru host: dahil
            {"name": "degnekci", "host": HOST},                                   # uzak "beyin": bizim beynimiz değil
            {"name": "varaka1", "host": HOST},                                    # uzak servis
            {"name": "zzz", "host": HOST},                                        # uzak kayıtsız
            {"name": "loc", "host": HOST},                                        # yerel projenin uzak adaşı
            {"name": "oiso", "host": "yuhem"},                                    # yanlış host
        ]
        self.assertEqual(self.names(rows), [("local", "loc"), ("local", "adhoc"), (HOST, "oiso")])

    def test_stale_host_rows_drop(self):
        self.assertEqual(self.names([{"name": "oiso", "host": HOST}], fresh=()), [])

    def test_index_hosts_skip_local_and_conflicts(self):
        idx = sw.build_ownership_index({"default": ["a", "b", "c"], "kitap": ["c"]},
                                       hosts={"default": {"a": HOST, "b": "local", "c": HOST}})
        self.assertEqual(idx["hosts"], {"a": HOST})
        w = sw.world_for("kitap", idx)
        self.assertEqual((w.host_of("a"), w.host_of("b"), w.host_of("c")), (HOST, "", ""))
        self.assertEqual(sw.build_ownership_index({"default": ["a"]})["hosts"], {})
        self.assertEqual(sw.World().unavailable, frozenset())


def _cfg(**kw):
    return dataclasses.replace(sw.Config(), **kw)


class TestPlanTickRemote(unittest.TestCase):
    def setUp(self):
        self.projects = {"oiso": sw.Project(name="oiso", phase="planned", cadence_minutes=60, host=HOST),
                         "a": sw.Project(name="a", phase="planned", cadence_minutes=60)}
        idx = sw.build_ownership_index({"default": list(self.projects)}, hosts={"default": {"oiso": HOST}})
        self.world = sw.world_for("default", idx)
        self.down = dataclasses.replace(self.world, unavailable=frozenset({"oiso"}))

    def test_unavailable_project_is_not_started_nor_forgotten(self):
        cfg = _cfg(max_starts_per_tick=2)
        acts, st = sw.plan_tick([], self.projects, {"ho_pending": {"oiso": 1.0}, "done_pending": {"oiso": "oiso"}},
                                cfg, 100000.0, [], [], world=self.down)
        self.assertEqual([(a.kind, a.name) for a in acts], [("start", "a")])
        self.assertIn("oiso", st["ho_pending"])                   # host kapalı: devir izi korunur, respawn YOK
        self.assertEqual(st["done_pending"], {"oiso": "oiso"})
        acts, st = sw.plan_tick([], self.projects, {"ho_pending": {"oiso": 1.0}}, cfg, 100000.0, [], [], world=self.world)
        self.assertIn(("respawn", "oiso"), [(a.kind, a.name) for a in acts])   # erişilebilir: eski davranış

    def test_pending_answer_for_unavailable_project_neither_starts_nor_blocks(self):
        q = sw.Question(id="q1", project="oiso", text="?", created_at=1.0, status="answered", answer="evet", answered_at=2.0)
        acts, _ = sw.plan_tick([], self.projects, {}, _cfg(), 100000.0, [q], [], world=self.down)
        self.assertNotIn(("start", "oiso"), [(a.kind, a.name) for a in acts])
        items = sw.review_items([], self.projects, _cfg(), 100000.0, [q], [], world=self.down)
        self.assertEqual([i for i in items if i["kind"] == "blocked"], [])

    def test_remote_session_counts_for_max_active(self):
        v = _view("oiso", host=HOST, subagent_unknown=True)
        acts, _ = sw.plan_tick([v], self.projects, {}, _cfg(max_active=1), 100000.0, [], [], world=self.world)
        self.assertNotIn("start", [a.kind for a in acts])
        acts, _ = sw.plan_tick([v], self.projects, {}, _cfg(max_active=2), 100000.0, [], [], world=self.world)
        self.assertIn(("start", "a"), [(a.kind, a.name) for a in acts])

    def test_subagent_unknown_defers_done_and_shutdown_handover(self):
        v = _view("oiso", host=HOST, subagent_unknown=True, last_assistant="bitti\nSTEWARD-DONE")
        acts, st = sw.plan_tick([v], self.projects, {}, _cfg(), 100000.0, [], [], world=self.world)
        self.assertNotIn("stop", [a.kind for a in acts])
        self.assertEqual(st["done_pending"], {"oiso": "oiso"})
        acts, st = sw.plan_tick([v], self.projects, st, _cfg(), 100100.0, [], [], world=self.world)
        self.assertNotIn("stop", [a.kind for a in acts])          # bilinmiyor = boşta değil: ertelenmiş DONE da bekler
        acts, sd, done = sw.plan_shutdown([v], self.projects, {}, _cfg(), 100000.0, world=self.world)
        self.assertEqual(acts, [])
        self.assertEqual(sd["items"]["oiso"]["stage"], "wait")

    def test_answer_delivery_still_allowed_with_unknown_subagent(self):
        v = _view("oiso", host=HOST, subagent_unknown=True)
        q = sw.Question(id="q1", project="oiso", text="?", created_at=1.0, status="answered", answer="evet", answered_at=2.0)
        acts, _ = sw.plan_tick([v], self.projects, {}, _cfg(), 100000.0, [q], [], world=self.world)
        self.assertIn(("deliver_answer", "oiso"), [(a.kind, a.name) for a in acts])


# ── depo: host alanı, doğrulama, host değişimi ──────────────────────────────

class TestProjectHost(_Remote):
    def test_old_records_load_as_local(self):
        os.makedirs(sw.STEWARD_DIR, exist_ok=True)
        with open(sw.PROJECTS_JSON, "w", encoding="utf-8") as f:
            json.dump({"eski": {"phase": "planned"}, "elle": {"phase": "planned", "host": "local"}}, f)
        ps = sw.load_projects()
        self.assertEqual((ps["eski"].host, ps["elle"].host), ("", ""))
        self.assertEqual(sw.ownership_index(fresh=True)["hosts"], {})

    def test_validation_and_normalization(self):
        with self.assertRaises(sw.HostChangeRefused):
            sw.upsert_project("oiso", host="kayitsiz")
        self.assertNotIn("oiso", sw.load_projects())
        self.assertEqual(sw.upsert_project("oiso", host=HOST).host, HOST)          # yeni projede çalışma denetimi yok
        self.assertEqual(sw.upsert_project("yerel", host="local").host, "")
        self.assertEqual(sw.ownership_index(fresh=True)["hosts"], {"oiso": HOST})
        self.assertEqual(sw.upsert_project("oiso", goal="g").host, HOST)           # host verilmeyen güncelleme korur

    def test_host_change_needs_a_stopped_project_or_force_and_clears_state(self):
        sw.upsert_project("oiso", phase="planned")
        sw.upsert_project("diger", phase="planned")
        sw.save_state({"ho_pending": {"oiso": 1.0, "diger": 1.0}, "seen_assistant": {"oiso20261021": "x", "diger": "y"},
                       "preamble_sent": {f"{HOST}:oiso": 5.0, "oiso": 4.0}, "done_pending": {"oiso_1": "oiso"},
                       "last_directive_at": {"oiso": 3.0}})
        for running in (True, None):
            with self.assertRaises(sw.HostChangeRefused):
                sw.upsert_project("oiso", host=HOST, running=lambda r=running: r)
        with self.assertRaises(sw.HostChangeRefused):
            sw.upsert_project("oiso", host=HOST)                                    # denetim verilmedi = bilinmiyor
        self.assertEqual(sw.load_projects()["oiso"].host, "")
        p = sw.upsert_project("oiso", host=HOST, running=lambda: False)
        self.assertEqual(p.host, HOST)
        st = sw.load_state()
        self.assertEqual(st["ho_pending"], {"diger": 1.0})
        self.assertEqual(st["seen_assistant"], {"diger": "y"})
        self.assertEqual(st["preamble_sent"], {})
        self.assertEqual(st["done_pending"], {})
        self.assertEqual(st["last_directive_at"], {"oiso": 3.0})                   # yalnız `_HOST_STATE_KEYS`
        self.assertTrue(self.log("project_host"))
        self.assertEqual(sw.upsert_project("oiso", host="local", force=True).host, "")   # force: denetim yok

    def test_ownership_lock_first(self):
        sw.upsert_project("oiso")
        order = []
        orig = sw._flock

        def rec(path, timeout=None):
            order.append(os.path.basename(path))
            return orig(path, timeout)

        with mock.patch.object(sw, "_flock", rec):
            sw.upsert_project("oiso", host=HOST, force=True)
        self.assertEqual(order[:2], [".ownership.lock", ".lock"])


# ── motor: görünüm, observe/act, host kapalı ────────────────────────────────

class TestEngineRemote(_Remote):
    def setUp(self):
        super().setUp()
        sw.upsert_project("oiso", phase="planned", cadence_minutes=60, host=HOST)

    def test_views_come_from_cache_and_term_chat(self):
        self.settings()
        self.local_rows = [_row("oiso", host="local", cwd="/home/x/oiso"), _row("loc", host="local")]
        self.fake.set(HOST, [_row("oiso", context={"tokens": 1234}, cache={"age": 20}), _row("degnekci"),
                             _row("kapali", running=False)])
        self.fake.chat[(HOST, "oiso")] = "selam\nSTEWARD-ASK: hangi bölüm?"
        views = ws._collect_views(settings.steward_config())
        by = {(v.host, v.name): v for v in views}
        self.assertEqual(sorted(by), [("local", "loc"), (HOST, "oiso")])
        v = by[(HOST, "oiso")]
        self.assertEqual((v.context_tokens, v.history_size, v.started_at, v.subagent_unknown), (1234, 50, 0.0, True))
        self.assertAlmostEqual(v.last_activity, time.time() - 20, delta=5)
        self.assertEqual(v.last_assistant, "selam\nSTEWARD-ASK: hangi bölüm?")
        self.assertEqual([g for g in self.fake.gets if g[0] == "/api/term/chat"],
                         [("/api/term/chat", HOST, {"name": "oiso", "mode": "last"})])
        self.fake.set(HOST, [_row("oiso", context=None, cache=None)])
        v = [x for x in ws._collect_views(settings.steward_config()) if x.host == HOST][0]
        self.assertEqual((v.context_tokens, v.history_size, v.last_activity), (None, None, 0.0))   # bilinmiyor

    def test_observe_records_would_with_host_and_never_posts(self):
        self.settings()
        self.fake.set(HOST, [_row("oiso", context={"tokens": 400000})])
        self.fake.chat[(HOST, "oiso")] = "STEWARD-ASK: hangi bölüm?"
        res = ws.tick_once("manual")
        self.assertTrue(res["ok"], res)
        self.assertIn({"kind": "handover", "name": "oiso", "reason": res["dry"][0]["reason"], "dry": True, "host": HOST},
                      res["dry"])
        would = self.log("would:handover")
        self.assertEqual((would[0]["name"], would[0]["host"]), ("oiso", HOST))
        self.assertEqual(self.fake.posts, [])
        self.assertEqual(self.calls, [])
        self.assertEqual([q.project for q in sw.open_questions()], ["oiso"])       # kayıt eylemleri uzakta da çalışır

    def test_observe_start_and_answer_of_remote_project(self):
        self.settings()
        self.fake.set(HOST, [_row("oiso", running=False)])
        res = ws.tick_once("manual")
        self.assertEqual([(d["kind"], d.get("host")) for d in res["dry"]], [("start", HOST)])
        sw.save_state({})
        self.fake.set(HOST, [_row("oiso")])
        q = sw.add_question("oiso", "hangisi?", source="oiso")
        sw.answer_question(q.id, "ikincisi")
        res = ws.tick_once("manual")
        self.assertEqual([(d["kind"], d.get("host")) for d in res["dry"]], [("deliver_answer", HOST)])
        self.assertEqual(self.log("would:deliver_answer")[0]["host"], HOST)
        self.assertEqual((self.fake.posts, self.calls, self.touched), ([], [], []))

    def test_act_mode_denies_remote_while_remote_actions_off(self):
        # A3: `remote_actions` açıkken uzak eylem uygulanır (test_steward_remote_actions.py); kapalıyken act'te de red.
        self.settings(mode="act")
        self.fake.set(HOST, [_row("oiso", context={"tokens": 400000})])
        res = ws.tick_once("manual")
        self.assertEqual([(a["kind"], a["ok"]) for a in res["actions"]], [("handover", False)])
        denied = self.log("target_denied")
        self.assertEqual((denied[0]["host"], denied[0]["code"]), (HOST, "remote_disabled"))
        self.assertEqual((self.fake.posts, self.calls), ([], []))

    def test_act_mode_remote_project_does_not_eat_local_start_budget(self):
        self.settings(mode="act")
        sw.upsert_project("oiso", priority=1)
        sw.upsert_project("loc", phase="planned", cadence_minutes=60, priority=5)
        self.fake.set(HOST, [_row("oiso", running=False)])
        res = ws.tick_once("manual")
        self.assertEqual([a["kind"] + ":" + a["name"] for a in res["actions"]], ["start:loc"])
        self.assertEqual(self.touched, ["loc"])

    def test_host_down_keeps_state_and_drops_views(self):
        self.settings()
        sw.save_state({"ho_pending": {"oiso": 1.0}})
        for st in ({"ok": False}, {"ok": True, "age": 120}):
            self.fake.set(HOST, [_row("oiso")], ok=st["ok"], age=st.get("age", 1.0))
            self.assertEqual([v for v in ws._collect_views(settings.steward_config()) if v.host != "local"], [])
            res = ws.tick_once("manual")
            self.assertEqual(res["dry"], [])
            self.assertIn("oiso", sw.load_state()["ho_pending"])
        self.assertEqual(self.fake.gets, [])

    def test_last_assistant_reads_share_a_budget(self):
        self.fake.chat[(HOST, "fast")] = "ok"
        self.fake.slow["slow"] = 1.0
        t0 = time.monotonic()
        got = ws._remote_last_assistant([(HOST, "slow"), (HOST, "fast")], budget=0.2)
        self.assertLess(time.monotonic() - t0, 0.8)
        self.assertEqual(got, {(HOST, "fast"): "ok"})


# ── kapı: `_target` / `_gate` ───────────────────────────────────────────────

class TestTargetRemote(_Remote):
    def setUp(self):
        super().setUp()
        sw.upsert_project("oiso", phase="planned", host=HOST)
        sw.upsert_project("loc", phase="planned")

    def test_rules(self):
        self.settings(remote_actions="on")
        codes = lambda r: r and r.get("code")   # noqa: E731
        self.assertEqual(codes(ws._target("oiso", "", kind="stop")), "remote_destructive_pending")   # A3: yıkıcı yok (A4)
        self.assertEqual(codes(ws._target("oiso", "", kind="handover")), "host_down")   # host önbellekte yok: taze değil
        self.fake.set(HOST, [_row("oiso")])
        self.assertIsNone(ws._target("oiso", "", kind="handover"))                      # host verilmedi: projeninki
        self.assertIsNone(ws._target("oiso", "", kind="handover", host=HOST))
        self.assertEqual(codes(ws._target("oiso", "", kind="stop", host="local")), "host_mismatch")   # yerel adaş: red
        self.assertEqual(codes(ws._target("oiso20261021", "", kind="stop", host="local")), "host_mismatch")
        self.assertIsNone(ws._target("oiso20261021", "engine", kind="handover"))
        self.assertEqual(codes(ws._target("oiso", "", kind="restart", host=HOST)), "remote_destructive_pending")
        self.assertEqual(codes(ws._target("oiso", "", kind="stop", host="yok")), "unknown_host")
        self.assertEqual(codes(ws._target("loc", "", kind="stop", host=HOST)), "host_mismatch")
        self.assertEqual(codes(ws._target("zzz", "", kind="stop", host=HOST)), "host_mismatch")   # kayıtsız uzak
        self.assertEqual(codes(ws._target("degnekci", "engine", kind="stop", host=HOST)), "host_mismatch")
        self.assertIsNone(ws._target("loc", "engine", kind="stop"))
        self.assertIsNone(ws._target("loc", "", kind="stop", host="local"))
        self.assertIsNone(ws._target("zzz", "", kind="stop"))                                  # ad hoc yerel: eski davranış

    def test_http_endpoints(self):
        self.settings()
        r = ws.http_post("/api/steward/stop", {"name": "oiso", "host": "local"})
        self.assertEqual((r["ok"], r["code"]), (False, "host_mismatch"))
        r = ws.http_post("/api/steward/stop", {"name": "oiso"})
        self.assertEqual((r["ok"], r["code"]), (False, "remote_disabled"))
        r = ws.http_post("/api/steward/handover", {"name": "oiso", "host": HOST})
        self.assertEqual(r["code"], "remote_disabled")
        r = ws.http_post("/api/steward/handover", {"name": "oiso", "actor": "brain", "reason": "dolu"})
        self.assertEqual((r["ok"], r.get("dry"), r.get("host")), (True, True, HOST))           # observe beyni: kuru
        self.assertEqual(self.log("would:handover")[0]["host"], HOST)
        self.settings(mode="act")
        r = ws.http_post("/api/steward/directive", {"name": "oiso", "actor": "brain", "text": "x"})
        self.assertEqual((r["ok"], r["code"]), (False, "remote_disabled"))
        self.assertEqual((self.calls, self.touched, self.fake.posts), ([], [], []))


# ── uzak projede yerel dosya sistemi korumaları ─────────────────────────────

class TestLocalFsGuards(_Remote):
    def setUp(self):
        super().setUp()
        self.local_dir = os.path.join(self.dir.name, "oiso")       # aynı adlı YEREL klasör (adaş): dokunulmamalı
        os.makedirs(self.local_dir)
        with open(os.path.join(self.local_dir, "TODO.md"), "w", encoding="utf-8") as f:
            f.write("# yerel\n")
        self.fleet = {"oiso": {"cwd": self.local_dir, "cli": "claude"}}
        sw.upsert_project("oiso", phase="planned", host=HOST)
        self.settings(card_refresh="on")

    def test_cwd_and_cards(self):
        self.assertEqual(ws._project_cwd("oiso"), "")
        self.assertEqual(ws._cwd_resolver()("oiso"), "")
        with mock.patch.object(ws, "summarize_card", lambda *a, **k: (_ for _ in ()).throw(AssertionError("kart"))):
            self.assertEqual(ws.refresh_due_cards(settings.steward_config(), limit=10), [])
            self.assertFalse(ws.refresh_card("oiso", settings.steward_config())["ok"])
        self.assertIsNone(sw.load_card("oiso"))

    def test_idea_export_register_file_context(self):
        idea = sw.add_idea("yeni fikir", source="oiso")
        r = ws.http_post("/api/steward/idea/export", {"id": idea.id, "kind": "todo"})
        self.assertEqual((r["ok"], r.get("skipped")), (False, ["oiso"]))
        with open(os.path.join(self.local_dir, "TODO.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# yerel\n")
        newdir = os.path.join(self.dir.name, "yeni")
        for body in ({"name": "oiso", "cwd": self.local_dir}, {"name": "yeni", "cwd": newdir, "host": HOST}):
            r = ws.http_post("/api/steward/register", body)
            self.assertFalse(r["ok"])
            self.assertIn("remote project", r["error"])
        self.assertFalse(os.path.exists(newdir))
        self.assertFalse(os.path.exists(os.path.join(self.local_dir, "GOAL.md")))
        self.assertEqual(self.calls, [])
        self.assertFalse(ws.http_file("oiso", "TODO.md")["ok"])
        ctx = ws.http_context("oiso")
        self.assertEqual((ctx["host"], ctx["cwd"], ctx.get("docs"), ctx["git"]), (HOST, "", {}, ""))

    def test_project_for_session_skips_local_instance_registry(self):
        projects = sw.load_projects()
        with mock.patch.object(ws.inst_mod, "get_instance", lambda name: (_ for _ in ()).throw(AssertionError(name))):
            self.assertEqual(ws._project_for_session("oiso", projects, ws._world()).name, "oiso")
            self.assertEqual(ws._project_for_session("oiso20261021", projects).name, "oiso")


# ── proje kaydı ucu (`http_project_upsert`) ve CLI ──────────────────────────

class TestUpsertRemote(_Remote):
    def test_active_phase_needs_remote_roster(self):
        self.settings()
        self.fake.set(HOST, [_row("oiso", running=False)], closed=[_row("eski", running=False)])
        r = ws.http_post("/api/steward/project", {"name": "oiso", "phase": "planned", "host": HOST})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["project"]["host"], HOST)
        self.assertTrue(ws.http_post("/api/steward/project", {"name": "eski", "phase": "planned", "host": HOST})["ok"])
        r = ws.http_post("/api/steward/project", {"name": "yok", "phase": "planned", "host": HOST})
        self.assertIn("not in the roster of host", r["error"])
        self.fake.set(HOST, [_row("oiso2", running=False)], ok=False)
        r = ws.http_post("/api/steward/project", {"name": "oiso2", "phase": "planned", "host": HOST})
        self.assertFalse(r["ok"])
        self.assertTrue(ws.http_post("/api/steward/project", {"name": "fikir", "phase": "idea", "host": HOST})["ok"])

    def test_host_change_checks_running_sessions(self):
        self.settings()
        sw.upsert_project("oiso", phase="idea")
        self.fake.set(HOST, [_row("oiso")])
        r = ws.http_post("/api/steward/project", {"name": "oiso", "host": HOST})
        self.assertFalse(r["ok"])
        self.assertIn("running session", r["error"])
        self.fake.set(HOST, [_row("oiso", running=False)])
        self.live = [NS(name="oiso_1", cwd="/x", cli="claude", pid=1, sid=None, base="oiso")]
        self.assertFalse(ws.http_post("/api/steward/project", {"name": "oiso", "host": HOST})["ok"])   # yerelde çalışıyor
        self.live = []
        self.fake.hosts.pop(HOST)
        self.assertFalse(ws.http_post("/api/steward/project", {"name": "oiso", "host": HOST})["ok"])   # host bilinmiyor
        self.assertTrue(ws.http_post("/api/steward/project", {"name": "oiso", "host": HOST, "force": True})["ok"])
        r = ws.http_post("/api/steward/project", {"name": "oiso", "host": "local", "actor": "brain"})
        self.assertIn("brain cannot change", r["error"])
        self.assertEqual(sw.load_projects()["oiso"].host, HOST)
        self.assertFalse(ws.http_post("/api/steward/project", {"name": "oiso", "host": "kayitsiz", "force": True})["ok"])

    def test_cli_set_host_goes_through_the_panel(self):
        calls = []
        with mock.patch.object(cli, "_api", lambda port, m, path, body=None, sid="default":
                               calls.append((m, path, body)) or {"ok": True, "project": {"name": "oiso"}}):
            args = NS(name="oiso", phase=None, kind=None, goal=None, priority=None, cadence=None, note=None,
                      model=None, effort=None, host=HOST, force=True, port=1)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.cmd_set(args), 0)
        self.assertEqual(calls, [("POST", "/api/steward/project", {"name": "oiso", "host": HOST, "force": True})])
        self.assertNotIn("oiso", sw.load_projects())                      # CLI kendisi yazmadı


class TestWebHostsLastOk(unittest.TestCase):
    def test_last_ok_at_tracks_only_successes(self):
        name = "t_remote_lastok"
        self.addCleanup(lambda: [d.pop(name, None) for d in (wh._cache, wh._last_good, wh._fail_streak, wh._last_ok_at)])
        self.assertEqual(wh.last_ok_at(name), 0.0)
        wh._record_poll_result(name, {"ok": True, "error": None, "sessions": []})
        t = wh.last_ok_at(name)
        self.assertAlmostEqual(t, time.time(), delta=5)
        for _ in range(wh.CONSECUTIVE_FAILURES_BEFORE_ERROR + 1):
            wh._record_poll_result(name, {"ok": False, "error": "x", "sessions": []})
        self.assertEqual(wh.last_ok_at(name), t)
        self.assertFalse(wh.get_cached(name)["ok"])                  # bayat satır korunur ama ok:false → taze değil
        self.assertFalse(ws._host_fresh(dict(wh.get_cached(name), last_ok_at=t)))


if __name__ == "__main__":
    unittest.main()

"""Uzak proje → çalışan oturum çözümü (canlı hata 2026-10-21: `steward directive oiso "..."` ulak_31'de çalışan
`oiso20261017`yi görmeyip ikinci bir `oiso` oturumu başlatmıştı). Oturum adı = proje adı + tarih soneki (+ `_N`), her
yeni açılışta DEĞİŞİR; proje başına tek canlı oturum. `_remote_session`: 0 oturum → (izin varsa) PROJE adıyla başlatma;
1 oturum → her eylem (yönerge/term input, devir, durdurma, yeniden açmanın durdurma adımı, kapanma beklemesi, klasör
arama) o satırın GERÇEK adıyla (`exact: true`); 2+ oturum → `ambiguous_sessions`, hiçbir eylem, ASLA başlatma, tekrarsız
log. Tam oturum adı verilirse de satırdan doğrulanır. İnsan HTTP yolları ve motor aynı; başlatmadan sonra aynı tick'te
ikinci başlatma yok. Yerel yol değişmedi.

Gerçek ağ/uzak host/tmux/servis/`spawn_session` YOK: `ws._remote` sahte host (`DatedHost`: `/api/start` yeni oturuma
tarihli ad verir, uzak taraf gibi), `web_hosts._http_json`/`_http_raw` ve `ws.spawn_session` AssertionError'a bağlı,
`hosts.HOSTS_JSON` ve değnekçi dizini geçici (`_Tmp`). Gerçek settings.json sha256'sı modül başında/sonunda
karşılaştırılır.

Çalıştırma: python3 -m unittest discover -s py/tests"""
import hashlib
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_steward_remote import HOST, _row  # noqa: E402
from test_steward_remote_destructive import StopHost, _Destructive  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None
NEW = "20261021"        # sahte uzak tarafın yeni oturuma verdiği tarih soneki


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


def _facts(text=""):
    return {"running": True, "started_age_s": 600.0, "subagent_active": False, "context_tokens": 1000,
            "last_assistant": text}


class DatedHost(StopHost):
    """StopHost + uzak tarafın ad kuralı: `/api/start {"name": "oiso"}` yeni oturumu `oiso20261021` adıyla açar.
    `lag=True`: başlatma başarılı döner ama poller önbelleği yeni satırı (henüz) göstermez."""

    def __init__(self):
        super().__init__()
        self.lag = False

    def post(self, path, host, body, timeout=None):
        res = super().post(path, host, body, timeout)
        if path == "/api/start" and res[0].get("ok") and host in self.hosts:
            rows = self.hosts[host]["sessions"]
            if self.lag:
                self.hosts[host]["sessions"] = [r for r in rows if r["name"] != body["name"]]
            else:
                for r in rows:
                    if r["name"] == body["name"]:
                        r["name"] = body["name"] + NEW
                        r["cwd"] = f"/srv/{body['name']}"
        return res


class _Resolve(_Destructive):
    def setUp(self):
        super().setUp()
        self.fake = DatedHost()
        for p in (mock.patch.object(ws, "_remote", self.fake),
                  mock.patch.object(ws, "_remote_sleep", self.fake.sleep)):
            p.start()
            self.addCleanup(p.stop)
        self.act()

    def rows(self, *names, **kw):
        self.fake.set(HOST, [_row(n, cwd="/srv/oiso") for n in names], **kw)
        for n in names:
            self.fake.facts[n] = _facts()

    def directive(self, name="oiso", **kw):
        return ws.http_post("/api/steward/directive", dict({"name": name, "text": "devam et"}, **kw))

    def inputs(self):
        return [(p[2]["name"], p[2]["exact"]) for p in self.posts("/api/term/input")]


# ── yönerge: tek tarihli oturum, oturum yok, iki oturum ──────────────────────

class TestDirective(_Resolve):
    def test_project_name_reaches_the_single_dated_session_without_any_start(self):
        self.rows("oiso20261017")
        r = self.directive("oiso")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["name"], r["host"]), ("oiso20261017", HOST))
        self.assertEqual(self.posts("/api/start"), [])                      # canlı hata: ikinci `oiso` AÇILMAZ
        self.assertEqual(self.inputs(), [("oiso20261017", True)])
        self.assertNotIn("host", self.posts()[0][2])
        st = sw.load_state()
        self.assertEqual(list(st["preamble_sent"]), [f"{HOST}:oiso20261017"])
        self.assertIn("oiso20261017", st["last_directive_at"])
        self.assertEqual(self.calls, [])                                     # yerel yol yok

    def test_engine_counts_a_dated_session_without_blueprint_as_running(self):
        self.rows("oiso20261017")                                            # `_row`: instance=False (blueprint yok)
        res = ws.tick_once("manual")
        self.assertEqual([a for a in res["actions"] if a["kind"] == "start"], [], res)   # "due" başlatma YOK
        self.assertEqual(self.posts("/api/start"), [])
        views = [v for v in ws._collect_views(ws.steward_config()) if v.host == HOST]
        self.assertEqual([(v.name, v.project) for v in views], [("oiso20261017", "oiso")])

    def test_no_running_session_starts_with_the_project_name(self):
        self.fake.set(HOST, [_row("oiso20261017", running=False)])          # eski oturum kapalı
        self.fake.facts["oiso" + NEW] = _facts()
        r = self.directive("oiso")
        self.assertTrue(r["ok"], r)
        model, effort = sw.phase_model_effort(sw.load_projects()["oiso"], ws.steward_config())
        self.assertEqual(self.posts("/api/start"),
                         [("/api/start", HOST, {"name": "oiso", "model": model, "effort": effort, "fresh": False}, 120.0)])
        self.assertEqual(self.inputs(), [("oiso" + NEW, True)])              # yeni (tarihli) adla
        self.assertEqual(r["name"], "oiso" + NEW)

    def test_two_running_sessions_are_ambiguous_and_nothing_is_posted(self):
        self.rows("oiso20261017", "oiso20261018")
        for name in ("oiso", "oiso20261017", "oiso"):                        # tam ad verilse de: proje belirsiz
            r = self.directive(name)
            self.assertEqual((r["ok"], r["code"], r["host"]), (False, "ambiguous_sessions", HOST), r)
            self.assertEqual(r["sessions"], ["oiso20261017", "oiso20261018"])
        for path in ("/api/steward/stop", "/api/steward/handover", "/api/steward/restart"):
            self.assertEqual(ws.http_post(path, {"name": "oiso"})["code"], "ambiguous_sessions", path)
        self.assertEqual(self.apply("start")["code"], "ambiguous_sessions")  # motor da ASLA başlatmaz
        self.assertEqual((self.posts(), self.calls), ([], []))
        logged = [(e["actor"], e["name"], e["kind"]) for e in self.log("remote_ambiguous")]
        self.assertEqual(logged.count(("human", "oiso", "directive")), 1)    # tekrarsız (aynı aktör/ad/sebep)
        self.assertIn(("engine", "oiso", "directive"), logged)
        self.assertEqual(self.log("remote_ambiguous")[0]["sessions"], ["oiso20261017", "oiso20261018"])

    def test_full_session_name_is_verified_against_the_rows(self):
        self.rows("oiso20261017")
        r = self.directive("oiso20261017")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.inputs(), [("oiso20261017", True)])
        self.fake.posts.clear()
        for path, body in (("/api/steward/directive", {"name": "oiso20261016", "text": "x"}),   # kapanmış eski ad
                           ("/api/steward/stop", {"name": "oiso20261016"}),
                           ("/api/steward/handover", {"name": "oiso20261016"})):
            r = ws.http_post(path, body)
            self.assertEqual((r["ok"], r["code"]), (False, "other_session_running"), path)
        self.assertEqual(self.posts(), [])                                   # eski ada yazılmaz, yanına oturum açılmaz

    def test_underscore_suffix_resolves(self):
        self.rows("oiso20261017_1")
        self.assertTrue(self.directive("oiso")["ok"])
        r = ws.http_post("/api/steward/stop", {"name": "oiso"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.inputs(), [("oiso20261017_1", True)])
        self.assertEqual(self.posts("/api/stop"), [("/api/stop", HOST, {"name": "oiso20261017_1", "exact": True}, 60.0)])

    def test_another_projects_prefix_does_not_mix_in(self):
        sw.upsert_project("oisox", phase="idea", host=HOST)
        self.rows("oiso20261017", "oisox20261017")
        self.assertTrue(self.directive("oiso")["ok"])                        # oisox'un oturumu oiso sayılmaz
        self.assertTrue(self.directive("oisox")["ok"])
        self.assertEqual(self.inputs(), [("oiso20261017", True), ("oisox20261017", True)])
        self.fake.posts.clear()
        self.rows("oisox20261017")                                           # oiso'nun oturumu yok, oisox'unki var
        self.fake.facts["oiso" + NEW] = _facts()
        self.assertTrue(self.directive("oiso")["ok"])
        self.assertEqual([p[2]["name"] for p in self.posts("/api/start")], ["oiso"])


# ── devir, durdurma, kapanma beklemesi, yeniden açma, restart: gerçek ad ──────

class TestDestructiveAndHandover(_Resolve):
    def test_handover_uses_the_real_name_and_records_it(self):
        self.rows("oiso20261017")
        r = ws.http_post("/api/steward/handover", {"name": "oiso"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.posts(), [("/api/handover", HOST, {"name": "oiso20261017", "exact": True}, 60.0)])
        self.assertEqual(list(sw.load_state()["ho_pending"]), ["oiso20261017"])   # plan_tick görünüm adıyla okur

    def test_stop_uses_the_real_name(self):
        self.rows("oiso20261017")
        r = ws.http_post("/api/steward/stop", {"name": "oiso"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.posts(), [("/api/stop", HOST, {"name": "oiso20261017", "exact": True}, 60.0)])
        self.assertEqual(r["name"], "oiso20261017")

    def test_wait_closed_watches_the_real_name(self):
        self.rows("oiso20261017")
        self.fake.close_on_stop = False
        r = ws._remote_stop_and_wait("oiso", HOST, ws._world(), "default", "engine")
        self.assertEqual((r["code"], r["error"].split(" still")[0]), ("stop_not_confirmed", "stop sent but 'oiso20261017'"))
        self.assertEqual(self.posts("/api/stop")[0][2]["name"], "oiso20261017")
        self.fake.close_on_stop = True
        self.fake.posts.clear()
        self.assertIsNone(ws._remote_stop_and_wait("oiso", HOST, ws._world(), "default", "engine"))
        self.assertTrue(ws._remote_wait_closed(HOST, "oiso20261017"))

    def test_respawn_after_handover_stops_real_name_starts_project_directs_new_name(self):
        self.rows("oiso20261017")
        self.fake.facts["oiso20261017"] = _facts("özet yazıldı. READY FOR HANDOVER")
        self.fake.facts["oiso" + NEW] = _facts()
        sw.save_state({"ho_pending": {"oiso20261017": time.time()}})
        res = ws.tick_once("manual")
        self.assertEqual([(a["kind"], a["name"], a["ok"]) for a in res["actions"]],
                         [("respawn", "oiso20261017", True)], res)
        stop, start, inp = self.posts()
        self.assertEqual(stop, ("/api/stop", HOST, {"name": "oiso20261017", "exact": True}, 60.0))
        self.assertEqual((start[0], start[2]["name"], start[2]["fresh"]), ("/api/start", "oiso", True))
        self.assertEqual((inp[0], inp[2]["name"], inp[2]["exact"]), ("/api/term/input", "oiso" + NEW, True))
        st = sw.load_state()
        self.assertNotIn("oiso20261017", st.get("ho_pending", {}))
        self.assertIn(f"{HOST}:oiso{NEW}", st["preamble_sent"])
        res = ws.tick_once("manual")                                          # sonraki tick: yeni ad çalışıyor, eylem yok
        self.assertEqual([a for a in res["actions"] if a["kind"] in ("respawn", "start")], [])
        self.assertEqual(len(self.posts("/api/start")), 1)
        self.assertEqual((self.calls, self.touched), ([], []))

    def test_human_restart_stops_real_name_then_starts_the_project(self):
        self.rows("oiso20261017")
        self.fake.facts["oiso" + NEW] = _facts()
        r = ws.http_post("/api/steward/restart", {"name": "oiso", "text": "baştan"})
        self.assertTrue(r["ok"], r)
        self.assertEqual([(p[0], p[2]["name"]) for p in self.posts()],
                         [("/api/stop", "oiso20261017"), ("/api/start", "oiso"), ("/api/term/input", "oiso" + NEW)])

    def test_engine_handover_on_dated_view_name(self):
        self.fake.set(HOST, [_row("oiso20261017", context={"tokens": 400000})])
        self.fake.facts["oiso20261017"] = dict(_facts(), context_tokens=400000)
        res = ws.tick_once("manual")
        self.assertEqual([(a["kind"], a["name"], a["ok"]) for a in res["actions"]], [("handover", "oiso20261017", True)])
        self.assertEqual(self.posts(), [("/api/handover", HOST, {"name": "oiso20261017", "exact": True}, 60.0)])


# ── aynı tick'te ikinci başlatma yok; okumalar gerçek adla ────────────────────

class TestStartOnceAndReads(_Resolve):
    def test_refresh_after_start_sees_the_new_session(self):
        self.fake.set(HOST, [])
        rt = ws._remote_snapshot([HOST])
        r1 = ws._ensure_running_remote("oiso", HOST, "m", "e", False, rt)
        self.assertEqual((r1["ok"], r1["started"], r1["name"]), (True, True, "oiso" + NEW))
        r2 = ws._ensure_running_remote("oiso", HOST, "m", "e", False, rt)   # görüntü yenilendi: çalışıyor
        self.assertEqual((r2["ok"], r2["started"], r2["name"]), (True, False, "oiso" + NEW))
        self.assertEqual(len(self.posts("/api/start")), 1)

    def test_lagging_cache_still_gets_no_second_start_in_the_tick(self):
        self.fake.set(HOST, [])
        self.fake.lag = True                                                  # önbellek yeni satırı göstermiyor
        rt = ws._remote_snapshot([HOST])
        p = sw.load_projects()["oiso"]
        r1 = ws._give_directive(p, "x", cfg=ws.steward_config(), host=HOST, rt=rt)
        self.assertFalse(r1["ok"])                                            # satır görünmedi: yönerge yok
        r2 = ws._give_directive(p, "y", cfg=ws.steward_config(), host=HOST, rt=rt)
        self.assertEqual((r2["ok"], r2["code"]), (False, "start_pending"))
        self.assertEqual(len(self.posts("/api/start")), 1)
        self.assertEqual(self.posts("/api/term/input"), [])

    def test_cwd_and_file_reads_use_the_real_name(self):
        self.fake.set(HOST, [_row("oiso20261017", cwd="/srv/oiso")])
        self.assertEqual(ws._remote_ref(HOST, "oiso"), ("oiso20261017", "/srv/oiso"))
        self.assertEqual(ws._remote_cwd(HOST, "oiso"), "/srv/oiso")
        ws.http_file("oiso", "TODO.md")
        self.assertEqual([g[2] for g in self.fake.gets if g[0] == "/api/files/read"],
                         [{"name": "oiso20261017", "path": "/srv/oiso/TODO.md"}])
        self.fake.set(HOST, [_row("oiso20261017"), _row("oiso20261018")])    # iki oturum: tahmin yok
        self.assertEqual(ws._remote_ref(HOST, "oiso"), ("", ""))
        self.fake.set(HOST, [], closed=[_row("oiso20261017", running=False, cwd="/srv/oiso")])   # yalnız kapalı satır
        self.assertEqual(ws._remote_ref(HOST, "oiso"), ("oiso20261017", "/srv/oiso"))
        sw.upsert_project("oisox", phase="idea", host=HOST)
        self.fake.set(HOST, [_row("oisox20261017", cwd="/srv/oisox")])       # başka projenin öneki karışmaz
        self.assertEqual(ws._remote_ref(HOST, "oiso"), ("", ""))


# ── yerel yol değişmedi ───────────────────────────────────────────────────────

class TestLocalUnchanged(_Resolve):
    def test_local_directive_still_uses_the_local_path(self):
        sw.upsert_project("loc", phase="planned")
        ensure = []
        with mock.patch.object(ws, "_ensure_running",
                               lambda name, **kw: ensure.append((name, kw.get("host", ""))) or {"ok": False, "error": "x"}):
            r = ws.http_post("/api/steward/directive", {"name": "loc", "text": "x"})
        self.assertEqual((r["ok"], ensure), (False, [("loc", "")]))
        self.assertEqual(self.posts(), [])


if __name__ == "__main__":
    unittest.main()

"""Uzak host'taki projeyi yönetme, A4 (TODO 2026-10-20 (14)): YIKICI uzak eylemler. Durdurma (`POST /api/stop`
`{"name", "exact": true}`, gövdede host YOK, 60 sn), yalnız host `exact_target` bildiriyorsa (yoksa `remote_too_old`,
tekrarsız) ve ön denetimde taze satır adı TAM, çalışıyor, "own" (beyin/kayıtsız DEĞİL) ise; `no_exact_match`/`ok: false`
uygulanmış sayılmaz ve kesiciyi açmaz; host başına tick'te tek yıkıcı eylem (fazlası sonraki tick'e ertelenir).
Yeniden açma bileşimi (durdur → önbellekten kapanma beklemesi → yeni konuşmayla başlat → yönerge; bir adım başarısızsa
sonraki YOK), restart (durdur + yönerge), insan HTTP kapıları, observe'da POST yok. Yerel durdurma/yeniden açma
değişmedi (altın testler ayrıca test_steward_engine_multi.py'de).

Gerçek ağ/uzak host/tmux/servis/`spawn_session` YOK: `ws._remote` sahte host (`StopHost`, POST'ları kaydeder, başarılı
durdurmada satırı kapatır), `web_hosts._http_json`/`_http_raw` ve `ws.spawn_session` AssertionError'a bağlı,
`hosts.HOSTS_JSON` ve değnekçi dizini geçici (`_Tmp`). Gerçek settings.json sha256'sı modül başında/sonunda karşılaştırılır.

Çalıştırma: python3 -m unittest discover -s py/tests"""
import hashlib
import os
import sys
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_steward_remote import HOST, _row  # noqa: E402
from test_steward_remote_actions import ActionHost, _Actions  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None
STOP = ("/api/stop", HOST, {"name": "oiso", "exact": True}, 60.0)
DOWN = ({"ok": False, "error": f"{HOST} unreachable: timed out"}, 200)


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


def _facts(text="", **kw):
    return dict({"running": True, "started_age_s": 600.0, "subagent_active": False, "context_tokens": 1000,
                 "last_assistant": text}, **kw)


class StopHost(ActionHost):
    """ActionHost + başarılı `/api/stop`: satır (tam adla) kapanır, poller önbelleği bunu hemen görür
    (`close_on_stop=False`: uzak taraf "tamam" dedi ama satır hiç kapanmıyor)."""

    def __init__(self):
        super().__init__()
        self.close_on_stop = True

    def post(self, path, host, body, timeout=None):
        res = super().post(path, host, body, timeout)
        if path == "/api/stop" and res[0].get("ok") and self.close_on_stop and host in self.hosts:
            for r in self.hosts[host]["sessions"]:
                if r["name"] == body["name"]:
                    r["running"] = False
        return res


class _Destructive(_Actions):
    def setUp(self):
        super().setUp()
        self.fake = StopHost()
        for p in (mock.patch.object(ws, "_remote", self.fake),
                  mock.patch.object(ws, "_remote_sleep", self.fake.sleep)):
            p.start()
            self.addCleanup(p.stop)

    def apply(self, kind, name="oiso", reason="t", rt=None):
        return ws._apply(sw.Action(kind, name, reason), ws.steward_config(), sw.load_projects(), ws._world(), rt=rt)

    def paths_posted(self):
        return [p[0] for p in self.posts()]


# ── durdurma: yol, gövde, koşullar ────────────────────────────────────────────

class TestRemoteStop(_Destructive):
    def test_steward_done_stop_path_body_timeout(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.fake.facts["oiso"] = _facts("iş bitti\nSTEWARD-DONE")
        res = ws.tick_once("manual")
        self.assertTrue(res["ok"], res)
        self.assertEqual([(a["kind"], a["ok"], a.get("host")) for a in res["actions"] if a["kind"] == "stop"],
                         [("stop", True, HOST)])
        self.assertEqual(self.posts(), [STOP])
        self.assertNotIn("host", self.posts()[0][2])
        self.assertEqual(self.calls, [])                                     # yerel `_act("stop")` (yerel adaş) YOK

    def test_no_exact_target_logs_remote_too_old_once_and_never_posts(self):
        self.act()
        self.fake.mode = "old"                                               # facts 404 → api 0
        self.fake.set(HOST, [_row("oiso")])
        for _ in range(3):
            self.assertEqual(self.apply("stop")["code"], "remote_too_old")
        self.assertEqual([(e["name"], e["host"], e["code"]) for e in self.log("remote_too_old")],
                         [("oiso", HOST, "remote_too_old")])                  # tekrarsız
        ws._CAPS.clear()
        self.fake.mode = "new"
        ws._caps_put(HOST, 1, ["session_facts"], time.time())                 # yeni api ama exact_target yok
        self.assertEqual(self.apply("stop")["code"], "remote_too_old")
        self.assertEqual(self.posts(), [])

    def test_unknown_capabilities_are_not_treated_as_supported(self):
        self.act()
        self.fake.mode = "down"                                              # yoklama ağ hatası: önbelleğe yazılmaz
        self.fake.set(HOST, [_row("oiso")])
        self.assertEqual(self.apply("stop")["code"], "caps_unknown")
        self.assertEqual(self.log("remote_too_old"), [])
        self.assertEqual(self.posts(), [])

    def test_precheck_exact_running_own_row(self):
        self.act()
        world = ws._world()
        # (tarihli tek oturum `oiso20261021` artık projeden çözülür ve TAM adıyla durdurulur:
        # test_steward_remote_session_resolve.py)
        self.fake.set(HOST, [_row("oiso", running=False)])                    # kapalı satır
        self.assertEqual(self.apply("stop")["code"], "no_exact_row")
        self.fake.set(HOST, [_row("oiso", instance=True, blueprint="degnekci")])   # blueprint beyni gösteriyor
        self.assertEqual(self.apply("stop")["code"], "not_own")
        self.fake.set(HOST, [_row("zzz"), _row("degnekci")])                  # kayıtsız uzak oturum / uzak "beyin"
        for name in ("zzz", "degnekci"):
            self.assertEqual(ws._remote_stop(name, HOST, world, "default", "engine")["code"], "not_own")
        self.assertEqual(self.posts(), [])

    def test_no_exact_match_is_not_applied_and_does_not_open_the_breaker(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        for reply in (({"ok": False, "error": "no_exact_match"}, 200), ({"ok": False, "error": "not_running"}, 200)):
            self.fake.posts.clear()
            self.fake.responses["/api/stop"] = [reply]
            rt = ws._remote_snapshot([HOST])
            res = ws._remote_stop("oiso", HOST, ws._world(), "default", "engine", rt)
            self.assertEqual((res["ok"], res["error"], res["host"]), (False, reply[0]["error"], HOST))
            self.assertFalse(rt.blocked(HOST))                                # devre kesici AÇILMADI
            self.assertIn(HOST, rt.succeeded)
        self.assertEqual([e["error"] for e in self.log("remote_stop_rejected")], ["no_exact_match", "not_running"])
        self.assertTrue(self.fake.hosts[HOST]["sessions"][0]["running"])      # satır duruyor: uygulanmış sayılmadı

    def test_transport_error_still_opens_the_breaker(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.fake.responses["/api/stop"] = [DOWN]
        rt = ws._remote_snapshot([HOST])
        self.assertEqual(ws._remote_stop("oiso", HOST, ws._world(), "default", "engine", rt)["code"], "host_down")
        self.assertTrue(rt.blocked(HOST))

    def test_observe_records_would_and_never_posts(self):
        self.settings(remote_actions="on")                                    # observe (varsayılan)
        self.fake.set(HOST, [_row("oiso")])
        self.fake.facts["oiso"] = _facts("STEWARD-DONE")
        res = ws.tick_once("manual")
        self.assertEqual([(d["kind"], d.get("host")) for d in res["dry"]], [("stop", HOST)])
        for path in ("/api/steward/stop", "/api/steward/restart"):
            r = ws.http_post(path, {"name": "oiso", "actor": "brain", "text": "x"})
            self.assertEqual((r["ok"], r.get("dry"), r.get("host")), (True, True, HOST))
        self.assertEqual({e["host"] for e in self.log("would:stop") + self.log("would:restart")}, {HOST})
        sw.save_state({"ho_pending": {"oiso": time.time()}})
        self.fake.facts["oiso"] = _facts("READY FOR HANDOVER")
        res = ws.tick_once("manual")
        self.assertEqual([(d["kind"], d.get("host")) for d in res["dry"]], [("respawn", HOST)])
        self.assertEqual((self.posts(), self.calls), ([], []))

    def test_remote_actions_off_and_down_host_are_denied(self):
        self.settings(mode="act")                                             # remote_actions kapalı
        self.fake.set(HOST, [_row("oiso")])
        self.assertEqual(self.apply("stop")["code"], "remote_disabled")
        self.assertEqual(self.apply("respawn")["code"], "remote_disabled")
        self.assertEqual(ws.http_post("/api/steward/stop", {"name": "oiso"})["code"], "remote_disabled")
        self.act()
        for kw in ({"ok": False}, {"age": 120}):                               # kapalı / bayat host
            self.fake.set(HOST, [_row("oiso")], **kw)
            self.assertEqual(self.apply("stop")["code"], "host_down")
            self.assertEqual(ws.http_post("/api/steward/restart", {"name": "oiso"})["code"], "host_down")
        self.assertEqual((self.posts(), self.calls), ([], []))

    def test_one_destructive_action_per_host_per_tick(self):
        self.act()
        sw.upsert_project("oiso2", phase="planned", cadence_minutes=60, host=HOST)
        sw.upsert_project("oiso3", phase="planned", cadence_minutes=60, host="yuhem")
        self.fake.set(HOST, [_row("oiso"), _row("oiso2")])
        self.fake.set("yuhem", [_row("oiso3")])
        for n in ("oiso", "oiso2", "oiso3"):
            self.fake.facts[n] = _facts("STEWARD-DONE")
        res = ws.tick_once("manual")
        stops = [(a["name"], a["ok"], a["detail"]) for a in res["actions"] if a["kind"] == "stop"]
        budget = f"one destructive action per host per tick ({HOST})"
        self.assertEqual(sorted(stops), [("oiso", True, ""), ("oiso2", False, budget), ("oiso3", True, "")])
        self.assertEqual(sorted((p[1], p[2]["name"]) for p in self.posts("/api/stop")),
                         [(HOST, "oiso"), ("yuhem", "oiso3")])               # başka host'un hakkı ayrı
        self.assertEqual(sw.load_state()["done_pending"], {"oiso2": "oiso2"})   # ertelendi, kaybolmadı
        self.assertEqual(self.log("remote_deferred")[0]["requeued"], True)
        res = ws.tick_once("manual")                                          # sonraki tick: ertelenen durdurma
        self.assertEqual([(a["kind"], a["name"], a["ok"]) for a in res["actions"] if a["kind"] == "stop"],
                         [("stop", "oiso2", True)])
        self.assertEqual(len(self.posts("/api/stop")), 3)

    def test_human_http_stop_gates(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.fake.set("yuhem", [_row("oiso")])
        codes = lambda body: ws.http_post("/api/steward/stop", body).get("code")   # noqa: E731
        self.assertEqual(codes({"name": "oiso", "host": "yuhem"}), "host_mismatch")
        self.assertEqual(codes({"name": "oiso", "host": "local"}), "host_mismatch")   # yerel adaşa dokunulmaz
        self.assertEqual(codes({"name": "zzz", "host": HOST}), "host_mismatch")      # kayıtsız uzak oturum
        self.assertEqual((self.posts(), self.calls), ([], []))
        r = ws.http_post("/api/steward/stop", {"name": "oiso", "host": HOST})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.posts(), [STOP])
        self.assertEqual([(e["name"], e["host"], e["ok"]) for e in self.log("stop")], [("oiso", HOST, True)])
        self.assertEqual(self.calls, [])


# ── yeniden açma (devirden sonra) ve restart bileşimi ─────────────────────────

class TestRemoteRespawn(_Destructive):
    def ready(self, names=("oiso",)):
        sw.save_state({"ho_pending": {n: time.time() for n in names}})
        for n in names:
            self.fake.facts[n] = _facts("özet yazıldı. READY FOR HANDOVER")

    def test_ready_after_handover_respawns_stop_start_directive_in_order(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.ready()
        res = ws.tick_once("manual")
        self.assertEqual([(a["kind"], a["ok"], a.get("host")) for a in res["actions"]], [("respawn", True, HOST)], res)
        self.assertEqual(self.paths_posted(), ["/api/stop", "/api/start", "/api/term/input"])
        stop, start, inp = self.posts()
        self.assertEqual(stop, STOP)
        model, effort = sw.phase_model_effort(sw.load_projects()["oiso"], ws.steward_config())
        self.assertEqual(start, ("/api/start", HOST, {"name": "oiso", "model": model, "effort": effort, "fresh": True},
                                 120.0))                                     # devirden sonra YENİ konuşma
        self.assertEqual((inp[2]["name"], inp[2]["exact"], inp[3]), ("oiso", True, 60.0))
        self.assertTrue(all("host" not in p[2] for p in self.posts()))
        self.assertEqual([e["step"] for e in self.log("remote_respawn")], ["done"])
        self.assertNotIn("oiso", sw.load_state().get("ho_pending", {}))
        self.assertEqual((self.calls, self.touched), ([], []))               # yerel yol hiç yürümedi
        res = ws.tick_once("manual")                                          # gürültü yok: ikinci tick'te yeniden açma yok
        self.assertEqual([a for a in res["actions"] if a["kind"] == "respawn"], [])
        self.assertEqual(len(self.posts("/api/stop")), 1)

    def test_stop_failure_means_no_start(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.fake.responses["/api/stop"] = [({"ok": False, "error": "no_exact_match"}, 200)]
        r = self.apply("respawn")
        self.assertEqual((r["ok"], r["step"], r["error"]), (False, "stop", "no_exact_match"))
        self.assertEqual(self.paths_posted(), ["/api/stop"])
        self.assertEqual([(e["step"], e["ok"]) for e in self.log("remote_respawn")], [("stop", False)])

    def test_stop_ok_but_row_never_closes_waits_bounded_then_stops(self):
        self.act()
        self.fake.close_on_stop = False
        self.fake.set(HOST, [_row("oiso")])
        r = self.apply("respawn")
        self.assertEqual((r["ok"], r["step"], r["code"]), (False, "stop", "stop_not_confirmed"))
        self.assertEqual(self.paths_posted(), ["/api/stop"])                  # başlatma/yönerge YOK
        self.assertEqual(self.fake.sleeps, int(ws.READY_TIMEOUT_SECONDS / ws.REMOTE_READY_POLL_SECONDS) - 1)
        self.assertEqual({g[0] for g in self.fake.gets}, {"/api/session/facts"})   # bekleme ağa gitmedi (yalnız yetenek)

    def test_start_failure_means_no_directive(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.fake.responses["/api/start"] = [({"ok": False, "error": "spawn failed"}, 200)]
        r = self.apply("respawn")
        self.assertEqual((r["ok"], r["step"]), (False, "start"))
        self.assertEqual(self.paths_posted(), ["/api/stop", "/api/start"])

    def test_session_already_gone_skips_stop(self):
        self.act()
        self.fake.set(HOST, [_row("oiso", running=False)])
        self.fake.facts["oiso"] = _facts()
        r = self.apply("respawn", reason="handover sent, session gone → start")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.paths_posted(), ["/api/start", "/api/term/input"])

    def test_old_host_respawn_is_refused_without_any_post(self):
        self.act()
        self.fake.mode = "old"
        self.fake.set(HOST, [_row("oiso")])
        r = self.apply("respawn")
        self.assertEqual((r["ok"], r["code"], r["step"]), (False, "remote_too_old", "stop"))
        self.assertEqual(self.posts(), [])

    def test_two_respawns_on_one_host_second_is_deferred_to_next_tick(self):
        self.act()
        sw.upsert_project("oiso2", phase="planned", cadence_minutes=60, host=HOST)
        self.fake.set(HOST, [_row("oiso"), _row("oiso2")])
        self.ready(("oiso", "oiso2"))
        res = ws.tick_once("manual")
        got = sorted((a["name"], a["ok"]) for a in res["actions"] if a["kind"] == "respawn")
        self.assertEqual(got, [("oiso", True), ("oiso2", False)])
        self.assertEqual(len(self.posts("/api/stop")), 1)
        self.assertIn("oiso2", sw.load_state()["ho_pending"])                 # ertelendi
        res = ws.tick_once("manual")
        self.assertEqual([(a["kind"], a["name"], a["ok"]) for a in res["actions"] if a["kind"] == "respawn"],
                         [("respawn", "oiso2", True)])
        self.assertEqual([p[2]["name"] for p in self.posts("/api/stop")], ["oiso", "oiso2"])

    def test_restart_stops_waits_then_directs(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.fake.facts["oiso"] = _facts()
        r = ws.http_post("/api/steward/restart", {"name": "oiso", "text": "baştan, daha dar", "reason": "boş iş"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.paths_posted(), ["/api/stop", "/api/start", "/api/term/input"])
        self.assertEqual(self.posts()[1][2]["fresh"], False)                  # restart: aynı konuşma (yerel ile aynı)
        self.assertIn("baştan, daha dar", self.posts()[2][2]["text"])
        self.assertEqual([(e["name"], e["host"]) for e in self.log("restart")], [("oiso", HOST)])
        self.assertEqual((self.calls, self.touched), ([], []))

    def test_restart_without_confirmed_stop_sends_nothing_more(self):
        self.act()
        self.fake.close_on_stop = False
        self.fake.set(HOST, [_row("oiso")])
        r = ws.http_post("/api/steward/restart", {"name": "oiso", "text": "x"})
        self.assertEqual((r["ok"], r["code"]), (False, "stop_not_confirmed"))
        self.assertEqual(self.paths_posted(), ["/api/stop"])
        self.assertEqual(self.log("restart")[0]["ok"], False)

    def test_restart_host_mismatch_is_denied(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.assertEqual(ws.http_post("/api/steward/restart", {"name": "oiso", "host": "local"})["code"],
                         "host_mismatch")
        self.assertEqual((self.posts(), self.calls), ([], []))


# ── yerel durdurma/yeniden açma değişmedi ─────────────────────────────────────

class TestLocalUnchanged(_Destructive):
    def setUp(self):
        super().setUp()
        sw.upsert_project("loc", phase="planned")
        self.ensure = []
        p = mock.patch.object(ws, "_ensure_running",
                              lambda name, **kw: self.ensure.append((name, kw)) or {"ok": False, "error": "no tmux here"})
        p.start()
        self.addCleanup(p.stop)

    def test_local_stop_and_respawn_use_the_local_callbacks(self):
        self.act()
        self.fake.set(HOST, [_row("oiso"), _row("loc")])                     # uzak adaş `loc` satırı yok sayılır
        self.assertEqual(self.apply("stop", "loc"), {"ok": True})
        with mock.patch.object(ws, "_running", lambda name: NS(name=name, cli="claude", pid=1) if name == "loc" else None):
            self.assertEqual(self.apply("respawn", "loc"), {"ok": False, "error": "no tmux here"})
        self.assertEqual(self.calls, [("stop", "loc"), ("stop", "loc")])
        self.assertEqual([(n, kw.get("fresh"), kw.get("host", "")) for n, kw in self.ensure], [("loc", True, "")])
        r = ws.http_post("/api/steward/stop", {"name": "loc"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.calls[-1], ("stop", "loc"))
        self.assertEqual(self.posts(), [])
        self.assertNotIn("host", self.log("stop")[0])


if __name__ == "__main__":
    unittest.main()

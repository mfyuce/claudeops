"""Uzak host'taki projeyi yönetme, A3 (TODO 2026-10-20 (14)): YIKICI OLMAYAN uzak eylemler. `_target`ın uzak kapıları
(`remote_actions`, kayıtlı + taze host, proje host'u = hedef host; yıkıcı türler A4'ten beri
test_steward_remote_destructive.py'de), devir (`/api/handover`), yönerge/cevap
iletimi (`/api/term/input`, `exact: true`), başlatma (`/api/start` + önbellekten hazır bekleme), `preamble_sent` anahtarı
`host:ad`, `proxy_action` zaman aşımı, devre kesici (tick içinde), geri çekilme (3 tick → 10 dk) ve tick'in tek tazelik
anlık görüntüsü. Yerel eylemler değişmedi (altın testler ayrıca test_steward_engine_multi.py'de).

Gerçek ağ/uzak host/tmux/servis/`spawn_session` YOK: `ws._remote` sahte host (`ActionHost`, POST'ları kaydeder),
`web_hosts._http_json`/`_http_raw` ve `ws.spawn_session` AssertionError'a bağlı, `hosts.HOSTS_JSON` ve değnekçi dizini
geçici (`_Tmp`). Gerçek settings.json sha256'sı modül başında/sonunda karşılaştırılır.

Çalıştırma: python3 -m unittest discover -s py/tests"""
import hashlib
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_steward_remote import HOST, _Remote, _row  # noqa: E402
from test_steward_remote_facts import FactsHost  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_hosts as wh, web_steward as ws  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None
_REAL_ENSURE_RUNNING = ws._ensure_running      # `_Remote` bunu sahteyle değiştirir; A3 testleri gerçek yolu koşturur
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


class ActionHost(FactsHost):
    """FactsHost + eylem POST'ları: `(yol, host, gövde, timeout)` kaydedilir; yanıt `responses[yol]` (sabit ya da sıra:
    liste baştan tüketilir), yoksa `{"ok": True}`. `/api/start` başarıyla dönünce satır çalışır ama meşgul görünür
    (`busy: True`): hazır bekleme önbellekteki satırın değişmesini bekler (`ready_after` uyku sonra `busy: False`)."""

    def __init__(self):
        super().__init__()
        self.responses = {}
        self.ready_after = 1
        self.sleeps = 0

    def post(self, path, host, body, timeout=None):
        self.posts.append((path, host, dict(body), timeout))
        r = self.responses.get(path)
        if isinstance(r, list):
            r = r.pop(0) if r else None
        res = r if r is not None else ({"ok": True}, 200)
        if path == "/api/start" and res[0].get("ok") and host in self.hosts:
            rows = [x for x in self.hosts[host]["sessions"] if x["name"] != body["name"]]
            rows.append(_row(body["name"], busy=True))
            self.hosts[host]["sessions"] = rows
        return res

    def sleep(self, seconds):
        """`ws._remote_sleep` yerine: uyku sayılır; `ready_after` uykudan sonra yeni oturum boşa düşer."""
        self.sleeps += 1
        if self.sleeps >= self.ready_after:
            for st in self.hosts.values():
                for r in st["sessions"]:
                    r["busy"] = False


class _Actions(_Remote):
    def setUp(self):
        super().setUp()
        self.fake = ActionHost()
        for p in (mock.patch.object(ws, "_remote", self.fake),
                  mock.patch.object(ws, "_ensure_running", _REAL_ENSURE_RUNNING),
                  mock.patch.object(ws, "_remote_sleep", self.fake.sleep)):
            p.start()
            self.addCleanup(p.stop)
        sw.upsert_project("oiso", phase="planned", cadence_minutes=60, goal="amac-metni", host=HOST)

    def act(self, **kw):
        self.settings(**dict({"mode": "act", "remote_actions": "on"}, **kw))

    def posts(self, path=None):
        return [p for p in self.fake.posts if path is None or p[0] == path]

    def answered(self, text="hangisi?", answer="ikincisi"):
        q = sw.add_question("oiso", text, source="oiso")
        sw.answer_question(q.id, answer)
        return q


# ── eylemler: yol, gövde, zaman aşımı ─────────────────────────────────────────

class TestRemoteActions(_Actions):
    def test_handover_path_body_timeout(self):
        self.act()
        self.fake.set(HOST, [_row("oiso", context={"tokens": 400000})])
        res = ws.tick_once("manual")
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.posts(), [("/api/handover", HOST, {"name": "oiso", "exact": True}, 60.0)])
        self.assertEqual([(a["kind"], a["ok"], a.get("host")) for a in res["actions"]], [("handover", True, HOST)])
        self.assertEqual(self.calls, [])                                    # yerel geri çağrı (yerel adaş) YOK

    def test_handover_needs_an_exact_running_row(self):
        self.act()
        self.fake.set(HOST, [_row("oiso20261021")])                          # yalnız tarihli adaş: tam ad yok
        self.assertFalse(ws._remote_handover("oiso", HOST)["ok"])
        self.fake.set(HOST, [_row("oiso", running=False)])
        self.assertFalse(ws._remote_handover("oiso", HOST)["ok"])
        self.assertEqual(self.posts(), [])
        self.fake.set(HOST, [_row("oiso")])
        r = ws.http_post("/api/steward/handover", {"name": "oiso"})          # insan: uzak yoldan
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.posts(), [("/api/handover", HOST, {"name": "oiso", "exact": True}, 60.0)])
        self.assertIn("oiso", sw.load_state()["ho_pending"])

    def test_answer_goes_through_term_input_exact_and_preamble_key_is_host_colon_name(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.fake.facts["oiso"] = {"running": True, "started_age_s": 600.0, "subagent_active": False,
                                   "context_tokens": 1000, "last_assistant": ""}
        self.answered()
        res = ws.tick_once("manual")
        self.assertEqual([(a["kind"], a["ok"]) for a in res["actions"]], [("deliver_answer", True)], res)
        (path, host, body, timeout), = self.posts()
        self.assertEqual((path, host, timeout, body["name"], body["exact"]), ("/api/term/input", HOST, 60.0, "oiso", True))
        self.assertNotIn("host", body)
        self.assertIn("ikincisi", body["text"])
        self.assertIn("amac-metni", body["text"])                           # ilk iletim: tam önsöz
        st = sw.load_state()
        self.assertEqual(list(st["preamble_sent"]), [f"{HOST}:oiso"])
        self.assertAlmostEqual(st["preamble_sent"][f"{HOST}:oiso"], time.time() - 600, delta=5)
        self.assertIn("oiso", st["last_directive_at"])                       # plan_tick adla okur
        self.assertTrue(all(q.delivered_at for q in sw.load_questions()))
        self.answered("ikinci soru?", "evet")                                 # aynı yaşam: kısa (compact) iletim
        ws.tick_once("manual")
        body2 = self.posts("/api/term/input")[1][2]
        self.assertIn("evet", body2["text"])
        self.assertNotIn("amac-metni", body2["text"])

    def test_unknown_born_sends_full_preamble_and_records_nothing(self):
        self.act()
        self.fake.mode = "old"                                                # eski host: facts 404
        self.fake.set(HOST, [_row("oiso")])
        sw.save_state({"preamble_sent": {f"{HOST}:oiso": time.time() - 600}})
        self.answered()
        ws.tick_once("manual")
        body = self.posts("/api/term/input")[0][2]
        self.assertIn("amac-metni", body["text"])
        self.assertAlmostEqual(sw.load_state()["preamble_sent"][f"{HOST}:oiso"], time.time() - 600, delta=5)

    def test_start_waits_on_the_poller_cache_without_network(self):
        self.act()
        self.fake.set(HOST, [_row("oiso", running=False)])
        self.fake.facts["oiso"] = {"running": True, "started_age_s": 3.0, "subagent_active": False}
        self.fake.ready_after = 3
        res = ws.tick_once("manual")
        self.assertEqual([(a["kind"], a["ok"]) for a in res["actions"]], [("start", True)], res)
        start, inp = self.posts()
        model, effort = sw.phase_model_effort(sw.load_projects()["oiso"], ws.steward_config())
        self.assertEqual(start, ("/api/start", HOST, {"name": "oiso", "model": model, "effort": effort, "fresh": False},
                                 120.0))
        self.assertEqual((inp[0], inp[2]["name"], inp[2]["exact"]), ("/api/term/input", "oiso", True))
        self.assertEqual(self.fake.sleeps, 3)                                  # 2 sn'lik önbellek yoklamaları
        self.assertEqual({g[0] for g in self.fake.gets}, {"/api/session/facts"})   # bekleme ağa gitmedi (yalnız yaş okuması)

    def test_start_ready_timeout_is_bounded(self):
        self.fake.set(HOST, [_row("oiso", running=False)])
        self.fake.ready_after = 10 ** 6                                       # hiç boşa düşmez
        self.act()
        res = ws._ensure_running("oiso", model="m", effort="e", host=HOST)
        self.assertEqual((res["ok"], res["started"], res["ready"]), (True, True, False))
        self.assertEqual(self.fake.sleeps, int(ws.READY_TIMEOUT_SECONDS / ws.REMOTE_READY_POLL_SECONDS) - 1)

    def test_start_is_not_attempted_on_a_down_host(self):
        self.fake.set(HOST, [], ok=False)
        self.assertEqual(ws._ensure_running("oiso", host=HOST)["error"], "host_down")
        self.assertEqual(self.posts(), [])

    def test_directive_endpoint_and_remote_reject_passes_through(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.fake.responses["/api/term/input"] = ({"ok": False, "error": "no_exact_match"}, 200)
        r = ws.http_post("/api/steward/directive", {"name": "oiso", "text": "devam et", "start_if_stopped": False})
        self.assertEqual((r["ok"], r["error"], r["host"]), (False, "no_exact_match", HOST))
        self.fake.responses.clear()
        r = ws.http_post("/api/steward/directive", {"name": "oiso", "text": "devam et"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(self.posts("/api/term/input")), 2)

    def test_not_tmux_backed_or_not_running_rows_are_not_sent(self):
        self.act()
        self.fake.set(HOST, [_row("oiso", tmux=False)])
        r = ws.http_post("/api/steward/directive", {"name": "oiso", "text": "x"})
        self.assertIn("not tmux-backed", r["error"])
        self.fake.set(HOST, [_row("oiso", running=False)])
        r = ws.http_post("/api/steward/directive", {"name": "oiso", "text": "x", "start_if_stopped": False})
        self.assertEqual(r["error"], "not running")
        self.assertEqual(self.posts(), [])


# ── kapılar ───────────────────────────────────────────────────────────────────

class TestRemoteGates(_Actions):
    def test_observe_records_would_and_never_posts(self):
        self.settings(remote_actions="on")                                    # observe (varsayılan)
        self.fake.set(HOST, [_row("oiso")])
        self.answered()
        res = ws.tick_once("manual")
        self.assertEqual([(d["kind"], d.get("host")) for d in res["dry"]], [("deliver_answer", HOST)])
        sw.save_state({})
        self.fake.set(HOST, [_row("oiso", context={"tokens": 400000})])
        res = ws.tick_once("manual")
        self.assertEqual([(d["kind"], d.get("host")) for d in res["dry"]], [("handover", HOST)])
        r = ws.http_post("/api/steward/directive", {"name": "oiso", "actor": "brain", "text": "x"})
        self.assertEqual((r["ok"], r.get("dry"), r.get("host")), (True, True, HOST))
        self.assertEqual(self.log("would:directive")[0]["host"], HOST)
        self.assertEqual((self.posts(), self.calls), ([], []))

    def test_remote_actions_off_denies_in_act_and_logs_once(self):
        self.settings(mode="act")
        self.fake.set(HOST, [_row("oiso")])
        self.answered()
        for _ in range(3):
            res = ws.tick_once("manual")
            self.assertEqual([(a["kind"], a["ok"]) for a in res["actions"]], [("deliver_answer", False)])
        denied = self.log("target_denied")
        self.assertEqual([(d["name"], d["code"]) for d in denied], [("oiso", "remote_disabled")])   # tekrarsız
        self.assertEqual(self.posts(), [])

    def test_mismatch_unknown_and_unregistered_are_denied(self):
        self.act()
        self.fake.set(HOST, [_row("oiso"), _row("zzz")])
        self.fake.set("yuhem", [_row("oiso")])
        codes = lambda body: ws.http_post("/api/steward/handover", body).get("code")   # noqa: E731
        self.assertEqual(codes({"name": "oiso", "host": "yuhem"}), "host_mismatch")
        self.assertEqual(codes({"name": "oiso", "host": "local"}), "host_mismatch")
        self.assertEqual(codes({"name": "oiso", "host": "yok"}), "unknown_host")
        self.assertEqual(codes({"name": "zzz", "host": HOST}), "host_mismatch")          # kayıtsız uzak oturum
        r = ws.http_post("/api/steward/directive", {"name": "zzz", "host": HOST, "text": "x"})
        self.assertEqual(r["code"], "host_mismatch")
        self.assertEqual((self.posts(), self.calls), ([], []))

    def test_down_or_stale_host_gets_no_actions(self):
        self.act()
        self.answered()
        for kw in ({"ok": False}, {"age": 120}):
            self.fake.set(HOST, [_row("oiso", context={"tokens": 400000})], **kw)
            res = ws.tick_once("manual")
            self.assertEqual(res["actions"], [])
            self.assertEqual(ws.http_post("/api/steward/handover", {"name": "oiso"})["code"], "host_down")
        self.assertEqual(self.posts(), [])

    def test_destructive_kinds_need_exact_target_on_the_host(self):
        # A4: yıkıcı türler artık uzakta uygulanabilir, ama `exact_target` bildirmeyen eski host'ta HİÇ gönderilmez
        # (ayrıntılı yıkıcı testler test_steward_remote_destructive.py'de).
        self.act()
        self.fake.mode = "old"                                                # facts 404 → api 0, yetenek yok
        self.fake.set(HOST, [_row("oiso")])
        for path in ("/api/steward/stop", "/api/steward/restart"):
            self.assertEqual(ws.http_post(path, {"name": "oiso"})["code"], "remote_too_old")
        cfg, projects = ws.steward_config(), sw.load_projects()
        for kind in ("stop", "respawn"):
            r = ws._apply(sw.Action(kind, "oiso", "t"), cfg, projects, ws._world())
            self.assertEqual(r["code"], "remote_too_old")
        self.assertEqual(self.log("would:stop"), [])
        self.assertEqual((self.posts(), self.calls, self.touched), ([], [], []))

    def test_local_actions_are_unchanged_next_to_a_remote_project(self):
        self.act()
        sw.upsert_project("loc", phase="planned")
        self.fake.set(HOST, [_row("oiso")])
        cfg, projects = ws.steward_config(), sw.load_projects()
        self.assertEqual(ws._apply(sw.Action("handover", "loc", "t"), cfg, projects, ws._world()), {"ok": True})
        self.assertEqual(ws._apply(sw.Action("stop", "loc", "t"), cfg, projects, ws._world()), {"ok": True})
        self.assertEqual(self.calls, [("handover", "loc"), ("stop", "loc")])
        self.assertEqual(self.posts(), [])


# ── dayanıklılık: devre kesici, geri çekilme, tek görüntü, zaman aşımı ───────

class TestRemoteResilience(_Actions):
    def setUp(self):
        super().setUp()
        sw.upsert_project("oiso2", phase="planned", cadence_minutes=60, host=HOST)

    def two_answers(self):
        self.fake.set(HOST, [_row("oiso"), _row("oiso2")])
        for p in ("oiso", "oiso2"):
            q = sw.add_question(p, f"{p} soru?", source=p)
            sw.answer_question(q.id, "evet")

    def test_breaker_stops_after_first_transport_error_in_a_tick(self):
        self.act()
        self.two_answers()
        self.fake.responses["/api/term/input"] = [DOWN]
        res = ws.tick_once("manual")
        self.assertEqual([(a["kind"], a["ok"]) for a in res["actions"]], [("deliver_answer", False)] * 2)
        self.assertEqual(len(self.posts()), 1)                                # ikinci eylem DENENMEDİ
        self.assertEqual(sorted(a["detail"] for a in res["actions"])[0], "host_down")
        self.assertEqual(ws._HOST_HEALTH[HOST]["streak"], 1)

    def test_404_and_app_level_reject_do_not_open_the_breaker(self):
        self.act()
        for first in (({"error": "not found"}, 404), ({"ok": False, "error": "not_running"}, 200)):
            self.fake.posts.clear()
            for q in sw.load_questions():
                sw.mark_delivered(q.id)
            self.two_answers()
            self.fake.responses["/api/term/input"] = [first]
            ws.tick_once("manual")
            self.assertEqual(len(self.posts("/api/term/input")), 2)          # ikinci eylem yine denendi
            self.assertEqual(ws._HOST_HEALTH[HOST]["streak"], 0)
        self.assertEqual(self.log("remote_unreachable"), [])

    def test_backoff_after_three_failed_ticks_and_single_state_events(self):
        self.act()
        sw.upsert_project("oiso2", phase="idea")                              # tek eylem: oiso'ya cevap iletimi
        self.fake.set(HOST, [_row("oiso")])
        self.answered()
        self.fake.responses["/api/term/input"] = [DOWN] * 3
        for _ in range(3):
            ws.tick_once("manual")
        self.assertEqual(len(self.posts()), 3)
        h = ws._HOST_HEALTH[HOST]
        self.assertAlmostEqual(h["until"], time.time() + ws.REMOTE_BACKOFF_SECONDS, delta=30)
        self.assertEqual([(e["host"], e["state"]) for e in self.log("remote_unreachable")], [(HOST, "down")])
        res = ws.tick_once("manual")                                          # geri çekilmede: görünüm yok, eylem yok
        self.assertEqual((res["actions"], len(self.posts())), ([], 3))
        self.assertEqual(ws.http_post("/api/steward/directive", {"name": "oiso", "text": "x"})["code"], "host_down")
        self.assertEqual(len(self.posts()), 3)
        h["until"] = time.time() - 1                                          # 10 dk geçti; host düzeldi
        ws.tick_once("manual")
        self.assertEqual(len(self.posts()), 4)
        self.assertEqual([e["state"] for e in self.log("remote_unreachable")], ["down", "up"])   # yalnız durum değişimi
        self.assertEqual(ws._HOST_HEALTH[HOST]["streak"], 0)

    def test_no_phone_notification_for_unreachable(self):
        self.act()
        self.fake.set(HOST, [_row("oiso")])
        self.answered()
        self.fake.responses["/api/term/input"] = [DOWN] * 3
        with mock.patch.object(ws, "_notify", side_effect=AssertionError("ntfy olmamalı")):
            for _ in range(3):
                ws.tick_once("manual")
        self.assertEqual(len(self.log("remote_unreachable")), 1)

    def test_one_freshness_snapshot_per_tick(self):
        self.settings(remote_actions="on")
        self.fake.set(HOST, [_row("oiso"), _row("oiso2", running=False)])
        seen = []
        orig = self.fake.status
        with mock.patch.object(self.fake, "status", lambda h: seen.append(h) or orig(h)):
            ws.tick_once("manual")
        self.assertEqual(seen, [HOST])

    def test_snapshot_drives_both_unavailable_and_views(self):
        self.fake.set(HOST, [_row("oiso")])
        cfg = ws.steward_config()
        world = ws._world()
        rt = ws._remote_snapshot([HOST])
        self.fake.set(HOST, [_row("oiso")], ok=False)                         # görüntüden sonra düştü: görüntü geçerli
        self.assertEqual(ws._with_availability(world, cfg, rt=rt).unavailable, frozenset())
        self.assertEqual([v.name for v in ws._remote_views(world, rt=rt)], ["oiso"])
        rt2 = ws._remote_snapshot([HOST])
        self.assertEqual(ws._with_availability(world, cfg, rt=rt2).unavailable, frozenset({"oiso", "oiso2"}))
        self.assertEqual(ws._remote_views(world, rt=rt2), [])

    def test_proxy_action_timeout_and_forced_local_host(self):
        sent = []

        def fake_http(method, url, body, timeout, dedup=False):
            sent.append((method, body, timeout))
            return 200, {"ok": True}, None

        with mock.patch.object(wh, "_http_json", fake_http):
            wh.proxy_action("/api/term/input", HOST, {"name": "oiso", "text": "x", "exact": True})
            wh.proxy_action("/api/term/input", HOST, {"name": "oiso", "text": "x", "exact": True}, timeout=60.0)
            ws._RemoteIO().post("/api/start", HOST, {"name": "oiso"}, timeout=120.0)
        self.assertEqual([t for _m, _b, t in sent], [wh.ACTION_TIMEOUT_SECONDS, 60.0, 120.0])
        self.assertEqual(wh.ACTION_TIMEOUT_SECONDS, 200.0)                     # panel yolunun varsayılanı değişmedi
        self.assertTrue(all(b["host"] == "local" for _m, b, _t in sent))      # ikinci sıçrama yapısal olarak yok

    def test_remote_post_refuses_a_body_with_host(self):
        with self.assertRaises(ValueError):
            ws._remote_post(HOST, "/api/term/input", {"name": "oiso", "host": HOST}, 60.0)
        self.assertEqual(self.posts(), [])


if __name__ == "__main__":
    unittest.main()

"""Çoklu değnekçi P4: çok kimlikli MOTOR (`web_steward`): `StewardContext` kayıt defteri, `tick_once(sid)`, sıralı
`tick_round`, makine geneli `max_starts_total`/`max_active_total`, kimlikli `_target` kapısı, global çözümle uyumlu
`_project_for_session`/`_running_names_for`, `ownership_conflict` olayı, `http_register` talep denetimi.
`default`'un motor çıktısı P3 altın kaydıyla birebir (`TestEngineGolden`).

Canlı servis/tmux/docker/gerçek `~/.claude/claudeops/` YOK: `_Tmp` geçici dizin, oturum işlemleri sahte geri çağrı.
Çalıştırma: python3 -m unittest discover -s py/tests"""
import dataclasses
import hashlib
import json
import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

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


def _view(name, **kw):
    base = dict(running=True, cwd="/tmp/x", cli="claude", busy=False, history_size=100, tmux=True,
                started_at=1000.0, last_activity=1000.0)
    base.update(kw)
    return sw.SessionView(name=name, **base)


class _Engine(_Tmp):
    """İki kimlik (`default`, `kitap`); oturum işlemleri sahte, açılış denemeleri `self.touched`'a düşer."""

    def setUp(self):
        super().setUp()
        ws._reset_contexts()
        ws._RECENT.clear()
        ws.invalidate_summary()
        self.addCleanup(ws._reset_contexts)
        self.calls = []
        self.touched = []
        self.views = []

        def stop(name, lang="tr"):
            self.calls.append(("stop", name))
            return {"ok": True}

        def handover(name, lang="tr"):
            self.calls.append(("handover", name))
            return {"ok": True}

        def register(name, cwd, model="", cli="", lang="tr"):
            self.calls.append(("register", name))
            return {"ok": True}

        ws.configure(status_payload=lambda: {"sessions": []}, fleet_status=lambda: {},
                     start=lambda *a, **k: {"ok": True}, stop=stop, handover=handover, register_project=register)
        patches = [
            mock.patch.object(ws, "_CARD_BACKGROUND", False),
            mock.patch.object(ws, "_collect_views", lambda cfg: list(self.views)),
            mock.patch.object(ws, "_running", lambda name: None),
            mock.patch.object(ws, "_ensure_running",
                              lambda name, **kw: self.touched.append(name) or {"ok": False, "error": "no tmux here"}),
            mock.patch.object(ws, "maybe_daily_summary", lambda cfg, now: None),
            mock.patch.object(ws.inst_mod, "get_instance", lambda name: None),
            mock.patch.object(ws.web_ws, "notify_status_changed", lambda: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def settings(self, default=None, kitap=None):
        settings.save_settings({
            "steward": dict({"enabled": "on", "mode": "act", "card_refresh": "off"}, **(default or {})),
            "stewards": {"kitap": dict({"enabled": "on", "mode": "act"}, **(kitap or {}))}})


class TestTwoIdentityTick(_Engine):
    def test_each_identity_acts_only_on_its_own_and_writes_only_its_own_files(self):
        self.settings(default={"max_starts_total": "2"})
        sw.upsert_project("a", phase="planned", cadence_minutes=60)
        sw.upsert_project("k", paths="kitap", phase="planned", cadence_minutes=60)
        self.views = [_view("a", running=False), _view("k", running=False)]
        res = ws.tick_round("timer")
        self.assertEqual([(r["sid"], [(a["kind"], a["name"]) for a in r["actions"]]) for r in res],
                         [("default", [("start", "a")]), ("kitap", [("start", "k")])])
        self.assertEqual(self.touched, ["a", "k"])
        self.assertEqual(set(sw.load_state()["last_directive_at"]), {"a"})
        self.assertEqual(set(sw.load_state("kitap")["last_directive_at"]), {"k"})
        self.assertEqual([e["name"] for e in sw.tail_log(50) if e["event"] == "action"], ["a"])
        self.assertEqual([e["name"] for e in sw.tail_log(50, "kitap") if e["event"] == "action"], ["k"])
        self.assertEqual(ws._ctx("kitap").recent[0]["name"], "k")
        self.assertEqual(ws._RECENT[0]["name"], "a")                    # default bağlamı = modül globali
        self.assertEqual(ws.summary(sid="kitap")["last_tick"]["actions"], 1)

    def test_markers_land_in_the_owners_store_adhoc_only_default(self):
        self.settings()
        sw.upsert_project("a", phase="planned", cadence_minutes=0)
        sw.upsert_project("k", paths="kitap", phase="planned", cadence_minutes=0)
        self.views = [_view("a", busy=True, last_assistant="STEWARD-ASK: a sorusu?"),
                      _view("k", busy=True, last_assistant="STEWARD-ASK: k sorusu?\nSTEWARD-IDEA: k fikri"),
                      _view("egy", busy=True, last_assistant="STEWARD-ASK: kayıtsız sorusu?")]
        ws.tick_round("timer")
        self.assertEqual(sorted(q.project for q in sw.load_questions()), ["a", "egy"])
        self.assertEqual([q.project for q in sw.load_questions("kitap")], ["k"])
        self.assertEqual(([i.text for i in sw.load_ideas()], [i.text for i in sw.load_ideas("kitap")]), ([], ["k fikri"]))

    def test_max_starts_total_is_shared_across_identities(self):
        self.settings(default={"max_starts_per_tick": "3", "max_starts_total": "2"}, kitap={"max_starts_per_tick": "3"})
        for n in ("a", "b", "c"):
            sw.upsert_project(n, phase="planned", cadence_minutes=60)
        sw.upsert_project("k", paths="kitap", phase="planned", cadence_minutes=60)
        self.views = [_view(n, running=False) for n in ("a", "b", "c", "k")]
        res = ws.tick_round("timer")
        self.assertEqual(len(self.touched), 2)                                     # 3 + 3 değil, makine geneli 2
        self.assertEqual([r["started"] for r in res], [2, 0])
        self.assertNotIn("k", self.touched)
        self.settings(default={"max_starts_total": "1"})                           # varsayılan tek geçiş
        self.touched.clear()
        ws.tick_round("timer")
        self.assertEqual(len(self.touched), 1)

    def test_max_active_total_counts_the_other_identity(self):
        self.settings(default={"max_active_total": "1", "max_starts_total": "2"})
        sw.upsert_project("a", phase="planned", cadence_minutes=0)
        sw.upsert_project("k", paths="kitap", phase="planned", cadence_minutes=60)
        self.views = [_view("a", busy=True), _view("k", running=False)]
        ws.tick_round("timer")
        self.assertEqual(self.touched, [])                                         # makine dolu: kitap açamaz

    def test_disabled_identity_is_skipped(self):
        self.settings(kitap={"enabled": "off"})
        sw.upsert_project("k", paths="kitap", phase="planned", cadence_minutes=60)
        self.views = [_view("k", running=False)]
        self.assertEqual([r["sid"] for r in ws.tick_round("timer")], ["default"])
        self.assertEqual(self.touched, [])
        self.assertEqual(sw.tail_log(10, "kitap"), [])

    def test_one_identity_failing_does_not_skip_the_other(self):
        self.settings(default={"max_starts_total": "2"})
        sw.upsert_project("a", phase="planned", cadence_minutes=60)
        sw.upsert_project("k", paths="kitap", phase="planned", cadence_minutes=60)
        self.views = [_view("a", running=False), _view("k", running=False)]

        def views(cfg):
            if cfg.sid == "default":
                raise RuntimeError("default patladı")
            return list(self.views)
        with mock.patch.object(ws, "_collect_views", views):
            res = ws.tick_round("timer")
        self.assertEqual([(r["sid"], r["ok"]) for r in res], [("default", False), ("kitap", True)])
        self.assertIn("default patladı", res[0]["error"])
        self.assertEqual(self.touched, ["k"])
        # tick_once'ın DIŞINA kaçan hata da (beklenmedik) turu düşürmez
        orig = ws.tick_once
        self.touched.clear()
        sw.save_state({}, "kitap")

        def tick(trigger, sid="default", **kw):
            if sid == "default":
                raise RuntimeError("kaçtı")
            return orig(trigger, sid, **kw)
        with mock.patch.object(ws, "tick_once", tick):
            res = ws.tick_round("timer")
        self.assertEqual([(r["sid"], r["ok"]) for r in res], [("default", False), ("kitap", True)])
        self.assertEqual(self.touched, ["k"])

    def test_manual_action_does_not_wait_for_another_identitys_tick(self):
        self.settings()
        sw.upsert_project("a", phase="planned", cadence_minutes=0)
        entered, release = threading.Event(), threading.Event()

        def views(cfg):
            if cfg.sid == "kitap":
                entered.set()
                release.wait(10)
            return []
        with mock.patch.object(ws, "_collect_views", views):
            th = threading.Thread(target=lambda: ws.tick_once("timer", "kitap"), daemon=True)
            th.start()
            try:
                self.assertTrue(entered.wait(5))
                t0 = time.monotonic()
                self.assertTrue(ws.http_post("/api/steward/stop", {"name": "a"})["ok"])          # insan, default
                self.assertTrue(ws.http_post("/api/steward/handover", {"name": "a", "actor": "brain"})["ok"])
                self.assertTrue(ws.tick_once("manual")["ok"])                                  # default tick'i
                self.assertLess(time.monotonic() - t0, 3.0)
                self.assertFalse(ws._ctx("kitap").lock.acquire(blocking=False))               # kitap hâlâ tick'te
            finally:
                release.set()
                th.join(10)
        self.assertEqual(self.calls, [("stop", "a"), ("handover", "a")])
        self.assertTrue(ws._ctx("kitap").lock.acquire(blocking=False))
        ws._ctx("kitap").lock.release()

    def test_restart_does_not_deadlock_on_its_own_lock(self):
        """`http_restart` kilit altında `http_directive`i çağırır: kilit yeniden girişli olmalı (düz Lock asılıyordu)."""
        self.settings()
        sw.upsert_project("a", phase="planned")
        done = []
        with mock.patch.object(ws, "_give_directive", lambda p, text, **kw: {"ok": True}):
            th = threading.Thread(target=lambda: done.append(ws.http_post("/api/steward/restart", {"name": "a", "text": "x"})),
                                  daemon=True)
            th.start()
            th.join(5)
        self.assertEqual(done, [{"ok": True}])


class TestIdentityGate(_Engine):
    def setUp(self):
        super().setUp()
        self.settings()
        sw.upsert_project("a")
        sw.upsert_project("ncs")
        sw.upsert_project("k", paths="kitap")
        sw.upsert_project("ncs2", paths="kitap")
        self.dcfg, self.kcfg = settings.steward_config(), settings.steward_config("kitap")

    def apply(self, kind, name, cfg):
        return ws._apply(sw.Action(kind, name, "t"), cfg, sw.load_projects(cfg.sid))

    def test_engine_of_one_identity_cannot_touch_the_other(self):
        self.assertFalse(self.apply("stop", "a", self.kcfg)["ok"])
        self.assertFalse(self.apply("stop", "k", self.dcfg)["ok"])
        self.assertFalse(self.apply("handover", "degnekci", self.kcfg)["ok"])        # başka kimliğin beyni
        self.assertFalse(self.apply("stop", "adhocsess", self.kcfg)["ok"])           # kayıtsız oturum
        self.assertEqual(self.calls, [])
        self.assertTrue(self.apply("stop", "k", self.kcfg)["ok"])
        self.assertTrue(self.apply("stop", "a", self.dcfg)["ok"])
        self.assertEqual(self.calls, [("stop", "k"), ("stop", "a")])
        self.assertEqual(sum(1 for e in sw.tail_log(50, "kitap") if e["event"] == "target_denied"), 3)

    def test_global_prefix_resolution(self):
        # `ncs2` (kitap) oturumu `Session.base` ile default'un `ncs`'ine İNMEZ (eski kod default'a izin verirdi)
        self.assertIsNotNone(ws._target("ncs2", "engine", sid="default"))
        self.assertIsNone(ws._target("ncs2", "engine", sid="kitap"))
        self.assertIsNone(ws._target("ncs20261019", "engine", sid="default"))
        self.assertIsNone(ws._project_for_session("ncs2", sw.load_projects(), ws._world()))
        self.assertEqual(ws._project_for_session("ncs2", sw.load_projects()).name, "ncs")    # world'süz eski yol
        live = [NS(name="ncs2", base="ncs"), NS(name="a_1", base="a")]
        self.assertEqual(ws._running_names_for(live, sw.load_projects(), ws._world()), {"ncs2", "a_1", "a"})
        self.assertIn("ncs", ws._running_names_for(live, sw.load_projects()))                 # world'süz eski yol
        self.assertIn("ncs2", ws._running_names_for(live, sw.load_projects("kitap"), ws._world("kitap")))

    def test_human_calls_are_unrestricted(self):
        self.assertTrue(ws.http_post("/api/steward/stop", {"name": "k"})["ok"])
        self.assertTrue(ws.http_post("/api/steward/handover", {"name": "ncs2"})["ok"])
        self.assertFalse(ws.http_post("/api/steward/stop", {"name": "k", "actor": "brain"})["ok"])   # default beyni
        self.assertEqual(self.calls, [("stop", "k"), ("handover", "ncs2")])

    def test_non_default_brain_is_not_driven_before_p5(self):
        brain = self.kcfg.brain_name
        self.assertEqual(brain, "degnekci_kitap")
        for kind in ("tour", "respawn", "handover", "stop"):
            self.assertFalse(self.apply(kind, brain, self.kcfg)["ok"], kind)
        self.assertFalse(ws.brain_start(self.kcfg)["ok"])
        self.assertFalse(ws.run_tour([], cfg=self.kcfg)["ok"])
        self.assertEqual((self.calls, self.touched), ([], []))


class TestConflictAndRegister(_Engine):
    def test_ownership_conflict_logged_once_a_day_and_in_status(self):
        self.settings()
        sw.upsert_project("dup", phase="planned", cadence_minutes=60)
        kp = sw.paths_for("kitap")
        os.makedirs(kp.root)
        with open(kp.projects, "w", encoding="utf-8") as f:     # elle düzenleme: aynı ad iki kimlikte
            json.dump({"dup": {"name": "dup", "phase": "planned", "cadence_minutes": 60}}, f)
        self.views = [_view("dup", running=False)]
        for _ in range(2):
            ws.tick_once("timer")
            ws.tick_once("timer", "kitap")
        self.assertEqual(self.touched, [])                                          # kimse yönetmez
        for sid in ("default", "kitap"):
            ev = [e for e in sw.tail_log(50, sid) if e["event"] == "ownership_conflict"]
            self.assertEqual([(e["name"], e["stewards"]) for e in ev], [("dup", ["default", "kitap"])], sid)
        ws.invalidate_summary()
        self.assertEqual(ws.summary()["ownership_conflicts"], ["dup"])
        self.assertEqual(ws.http_get("/api/steward/state", {})["summary"]["ownership_conflicts"], ["dup"])

    def test_no_conflict_key_without_conflicts(self):
        self.settings()
        sw.upsert_project("a", cadence_minutes=0)
        ws.tick_once("timer")
        ws.invalidate_summary()
        self.assertNotIn("ownership_conflicts", ws.summary())

    def test_register_checks_claim_before_side_effects_and_warns_on_prefix(self):
        self.settings()
        sw.upsert_project("ncs2", paths="kitap")
        sw.upsert_project("kx", paths="kitap")
        for name, needle in (("kx", "owned by steward 'kitap'"), ("degnekcix", "reserved")):
            cwd = os.path.join(self.dir.name, name)
            r = ws.http_post("/api/steward/register", {"name": name, "cwd": cwd, "goal": "g"})
            self.assertFalse(r["ok"])
            self.assertIn(needle, r["error"])
            self.assertFalse(os.path.exists(cwd), name)                             # klasör/GOAL.md açılmadı
        self.assertEqual(self.calls, [])                                            # roster'a da yazılmadı
        r = ws.http_post("/api/steward/register", {"name": "ncs", "cwd": os.path.join(self.dir.name, "ncs"), "goal": "g"})
        self.assertTrue(r["ok"], r)
        self.assertIn("ncs2 (kitap)", r["warning"])
        self.assertIn("ncs", sw.load_projects())
        self.assertNotIn("warning", ws.http_post("/api/steward/project", {"name": "zz"}))
        self.assertIn("ncs2 (kitap)", ws.http_post("/api/steward/project", {"name": "nc"})["warning"])
        r = ws.http_post("/api/steward/project", {"name": "kx"})
        self.assertFalse(r["ok"])
        self.assertIn("owned by steward 'kitap'", r["error"])


# ── default'un motor çıktısı = P3 altın kaydı (plan_tick'in world'süz eski çıktısı) ───────────────────────────

import test_steward_multi as _tm  # noqa: E402


class TestEngineGolden(_Tmp):
    """Altın senaryo `tick_once` (disk depo, `world` ile) üzerinden: uygulanan eylemler + kaydedilen state, P3 öncesi
    kodla kaydedilmiş `steward_golden_tick.json` ile birebir. Elle tick (`starts_left=None`) ve tek kimlik."""

    def test_default_tick_once_matches_golden(self):
        ws._reset_contexts()
        out = []
        for ck in _tm.GOLDEN_CFGS:
            cfg = dataclasses.replace(_tm._cfg(**ck), mode="act")
            sw.save_projects(_tm._golden_projects())
            sw.save_questions(_tm._golden_questions())
            sw.save_ideas(_tm._golden_ideas())
            sw.save_state({"ho_pending": {"oldgone": _tm.T0 - 99999}})
            for step in range(3):
                now = _tm.T0 + step * 1200
                got = []
                with mock.patch.object(ws, "steward_config", lambda sid="default": cfg), \
                        mock.patch.object(ws, "_collect_views", lambda c, s=step: _tm._golden_views(s)), \
                        mock.patch.object(ws, "_apply", lambda a, c, p, w=None: got.append(a) or {"ok": True}), \
                        mock.patch.object(ws.web_ws, "notify_status_changed", lambda: None), \
                        mock.patch.object(ws.time, "time", lambda: now):
                    res = ws.tick_once("manual", cards=False)
                self.assertTrue(res["ok"], res)
                out.append(_tm._ser(got, sw.load_state()))
        self.assertEqual(out, _tm._golden())


if __name__ == "__main__":
    unittest.main()

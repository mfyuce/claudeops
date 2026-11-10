"""L2 (sahip tanımı 10 Kas 2026): değnekçi YALNIZ kendi başlattığı / ilk açılışta benimsediği oturumu izler; sahibin
elle açtığı oturum `manual` sınıfıdır (hiçbir eylem, yanına ikinci oturum da yok). Canlı tmux/CLI YOK."""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402


def _view(name, **kw):
    base = dict(running=True, cwd="/tmp/x", cli="claude", busy=False, history_size=100, tmux=True,
                started_at=1000.0, last_activity=1000.0)
    base.update(kw)
    return sw.SessionView(name=name, **base)


def _world(owned=None, projects=("hcr", "tunnel")):
    return sw.world_for("default", sw.build_ownership_index({"default": list(projects)}), "degnekci", owned=owned)


class SessionClassTest(unittest.TestCase):
    def test_unrecorded_project_is_own(self):
        self.assertEqual(_world().session_class("hcr20261110_2"), "own")

    def test_recorded_name_own_other_name_manual(self):
        w = _world({"hcr": "hcr20261110_1"})
        self.assertEqual(w.session_class("hcr20261110_1"), "own")
        self.assertEqual(w.session_class("hcr20261110_2"), "manual")
        self.assertEqual(w.session_class("hcr"), "manual")
        self.assertEqual(w.session_class("tunnel20261110"), "own")       # başka proje etkilenmez

    def test_empty_record_means_every_session_is_manual(self):
        w = _world({"hcr": ""})
        self.assertEqual(w.session_class("hcr20261110_2"), "manual")

    def test_brain_never_manual(self):
        self.assertEqual(_world({"hcr": ""}).session_class("degnekci"), "brain_own")


class UpdateOwnedTest(unittest.TestCase):
    P = {"hcr": sw.Project(name="hcr"), "tunnel": sw.Project(name="tunnel")}

    def test_first_sight_rules(self):
        new, ch = sw.update_owned({}, [_view("hcr20261110_1")], _world(), self.P, 0.0)
        self.assertEqual(new, {"hcr": "hcr20261110_1", "tunnel": ""})
        self.assertEqual({c["project"]: c["how"] for c in ch}, {"hcr": "adopt", "tunnel": "none"})

    def test_two_sessions_ambiguous_hands_off(self):
        new, _ = sw.update_owned({}, [_view("hcr20261110_1"), _view("hcr20261110_2")], _world(), self.P, 0.0)
        self.assertEqual(new["hcr"], "")

    def test_recorded_project_untouched(self):
        new, ch = sw.update_owned({"hcr": "hcr20261110_1", "tunnel": ""}, [_view("hcr20261110_2")], _world(), self.P, 0.0)
        self.assertEqual((new["hcr"], ch), ("hcr20261110_1", []))

    def test_seeding_needs_evidence(self):
        views = [_view("hcr20261110_2", started_at=500.0), _view("tunnel20261110", started_at=500.0)]
        new, ch = sw.update_owned({}, views, _world(), self.P, 0.0, seeding=True,
                                  evidence=lambda n, p, t: n == "tunnel20261110")
        self.assertEqual(new, {"hcr": "", "tunnel": "tunnel20261110"})
        self.assertEqual({c["project"]: c["how"] for c in ch}, {"hcr": "seed_manual", "tunnel": "seed"})


class EvidenceTest(unittest.TestCase):
    def _ts(self, t):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))

    def test_rules(self):
        t0 = time.mktime(time.strptime("2026-11-10T14:19:29", "%Y-%m-%dT%H:%M:%S"))
        before = {"ts": self._ts(t0 - 3600), "event": "directive", "name": "hcr"}
        after = {"ts": self._ts(t0 + 60), "event": "directive", "name": "hcr"}
        observe = {"ts": self._ts(t0 + 60), "event": "would:keepwarm", "name": "hcr20261110_2"}
        failed = {"ts": self._ts(t0 + 60), "event": "stop", "name": "hcr20261110_2", "ok": False}
        exact = {"ts": self._ts(t0 - 99), "event": "action", "kind": "start", "name": "hcr20261110_2", "ok": True}
        self.assertFalse(sw.owned_evidence([before, observe, failed], "hcr20261110_2", "hcr", t0))
        self.assertTrue(sw.owned_evidence([after], "hcr20261110_2", "hcr", t0))
        self.assertTrue(sw.owned_evidence([exact], "hcr20261110_2", "hcr", t0))


class PlanTickManualTest(unittest.TestCase):
    def _cfg(self):
        c = sw.Config(enabled=True)
        c.done_handover = False
        return c

    def test_manual_session_holds_project_no_start_no_handover(self):
        projects = {"hcr": sw.Project(name="hcr", phase="planned", cadence_minutes=1)}
        w = _world({"hcr": "hcr20261110_1"}, projects=("hcr",))
        views = [_view("hcr20261110_2", context_tokens=900_000, history_size=99_999, model="claude-sonnet-5-5")]
        q = sw.Question(id="q1", project="hcr", text="?", created_at=1.0, status="answered", answer="evet",
                        answered_at=2.0)
        actions, _ = sw.plan_tick(views, projects, {}, self._cfg(), 100_000.0, [q], [], world=w)
        touched = [(a.kind, a.name) for a in actions if a.kind not in ("tour",)]
        self.assertEqual(touched, [], touched)

    def test_owned_dead_and_no_manual_starts(self):
        projects = {"hcr": sw.Project(name="hcr", phase="planned", cadence_minutes=1)}
        w = _world({"hcr": "hcr20261110_1"}, projects=("hcr",))
        actions, _ = sw.plan_tick([], projects, {}, self._cfg(), 100_000.0, [], [], world=w)
        self.assertIn(("start", "hcr"), [(a.kind, a.name) for a in actions])


class TargetAndEnsureTest(_Tmp):
    def setUp(self):
        super().setUp()
        sw.save_projects({"hcr": sw.Project(name="hcr", phase="planned")})
        sw.save_state({"owned": {"hcr": "hcr20261110_1"}})

    def test_target_denies_manual_session(self):
        self.assertIsNone(ws._target("hcr20261110_1", "engine"))
        self.assertIsNotNone(ws._target("hcr20261110_2", "engine"))
        self.assertIsNotNone(ws._target("hcr20261110_2", "brain"))

    def _sess(self, *names):
        from claudeops.session import Session
        return [Session(name=n, pid=1) for n in names]

    def test_ensure_running_refuses_beside_manual_session(self):
        with mock.patch.object(ws, "_scan", lambda: self._sess("hcr20261110_2")), \
                mock.patch.object(ws, "_act", side_effect=AssertionError("must not start")):
            res = ws._ensure_running("hcr")
        self.assertEqual(res.get("code"), "manual_session_running", res)

    def test_ensure_running_uses_owned_session(self):
        with mock.patch.object(ws, "_scan", lambda: self._sess("hcr20261110_1", "hcr20261110_2")), \
                mock.patch.object(ws, "_act", side_effect=AssertionError("must not start")):
            res = ws._ensure_running("hcr")
            live = [s.name for s in ws._live_sessions("hcr")]
        self.assertEqual((res.get("ok"), res.get("started")), (True, False), res)
        self.assertEqual(live, ["hcr20261110_1"])
        self.assertIsNone(ws._target("hcr", "brain"))      # proje ADIYLA direktif kapıdan geçer (oturum değil, proje)

    def test_start_records_the_new_session(self):
        sw.save_state({"owned": {"hcr": "hcr20261110_1"}})
        with mock.patch.object(ws, "_scan", lambda: []), \
                mock.patch.object(ws, "_act", lambda *a, **k: {"ok": True}), \
                mock.patch.object(ws, "_start_appeared", lambda n, s: True), \
                mock.patch.object(ws, "_wait_ready", lambda n, c: True), \
                mock.patch.object(ws, "_resume_lacks_ho", lambda n, c: ""), \
                mock.patch.object(ws, "_oversized_resume", lambda n, c: 0), \
                mock.patch.object(ws, "_launch_kwargs", lambda n, m, e: {}), \
                mock.patch.object(ws, "_project_cli", lambda n: "claude"):
            res = ws._ensure_running("hcr")
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(sw.load_state()["owned"]["hcr"], "hcr")

    def test_seed_request_seeds_by_evidence_once(self):
        sw.save_state({})
        req = os.path.join(os.path.dirname(sw.paths_for("default").log), ws.OWNED_SEED_REQUEST)
        os.makedirs(os.path.dirname(req), exist_ok=True)
        open(req, "w").close()
        views = [_view("hcr20261110_2", started_at=time.time() - 60)]
        w = ws._world("default")
        w2 = ws._maintain_owned(views, sw.load_projects(), w, sw.paths_for("default"), "default", time.time())
        self.assertEqual(w2.owned, {"hcr": ""})                 # kanıt yok: sahibin oturumu, benimsenmez
        self.assertTrue(sw.load_state().get("owned_seeded"))
        self.assertFalse(os.path.exists(req))


class OwnedCliTest(_Tmp):
    def test_set_and_clear(self):
        import types
        from claudeops.commands import steward as cli
        a = types.SimpleNamespace(steward="default", action="set", project="tunnel", session="tunnel20261110")
        with mock.patch.object(cli, "_sid", lambda args: "default"):
            self.assertEqual(cli.cmd_owned(a), 0)
            self.assertEqual(sw.load_state()["owned"], {"tunnel": "tunnel20261110"})
            a.action = "clear"
            self.assertEqual(cli.cmd_owned(a), 0)
        self.assertEqual(sw.load_state()["owned"], {})


if __name__ == "__main__":
    unittest.main()

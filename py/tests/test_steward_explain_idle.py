"""`explain_idle`: panelde proje başına "neden ilerlemiyor" (saf çekirdek) + ayar beyaz listesi + döngü koruması sıfırlama.
Her neden motorun karar yoluyla aynı koşuldan türer; canlı servis/tmux YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

NOW = 1_000_000.0


def _v(name="p", **kw):
    base = dict(running=True, cwd="/tmp/x", cli="claude", busy=False, tmux=True, started_at=1.0,
                last_activity=NOW - 4000, last_assistant="")
    base.update(kw)
    return sw.SessionView(name=name, **base)


def _q(**kw):
    base = dict(id="q1", project="p", text="soru?", created_at=NOW)
    base.update(kw)
    return sw.Question(**base)


class Explain(unittest.TestCase):
    def why(self, proj=None, views=(), state=None, cfg=None, questions=(), actions=(), **kw):
        proj = proj or sw.Project(name="p", phase="planned", cadence_minutes=60)
        cfg = cfg or sw.Config()
        return sw.explain_idle(proj, list(views), {proj.name: proj}, state or {}, cfg, NOW, list(questions), list(actions), **kw)["code"]

    def test_phase(self):
        self.assertEqual(self.why(sw.Project(name="p", phase="paused")), "phase_paused")
        self.assertEqual(self.why(sw.Project(name="p", phase="done")), "phase_done")

    def test_notes_wait_and_cadence(self):
        self.assertEqual(self.why(sw.Project(name="p", phase="planned", cadence_minutes=60, notes="BEKLEME: hukukçu")), "notes_wait")
        self.assertEqual(self.why(sw.Project(name="p", phase="planned", cadence_minutes=0)), "cadence_off")

    def test_questions(self):
        self.assertEqual(self.why(questions=[_q()]), "ask_owner")
        self.assertEqual(self.why(questions=[_q(status="answered", answer="x")]), "answer_pending")
        self.assertEqual(self.why(questions=[_q(status="answered", answer="x", delivered_at=5.0)]), "start_blocked")   # kuyruk: uğranmamış
        r = sw.explain_idle(sw.Project(name="p", phase="planned"), [], {}, {}, sw.Config(), NOW, [_q()])
        self.assertEqual(r["question_id"], "q1")
        self.assertIn("q1", r["detail"])

    def test_not_running_decisions(self):
        p = sw.Project(name="p", phase="planned", cadence_minutes=60, last_visit=NOW - 600)
        self.assertEqual(self.why(p), "cadence_wait")
        p = sw.Project(name="p", phase="planned", cadence_minutes=60, last_visit=NOW - 7200)
        self.assertEqual(self.why(p, actions=[sw.Action("start", "p", "due")]), "starting")
        self.assertEqual(self.why(p, state={"start_blocked": {"projects": ["p"], "reason": "max_starts"}}), "start_blocked")
        self.assertEqual(self.why(p, cfg=sw.Config(auto_start=False)), "auto_start_off")
        self.assertEqual(self.why(p, cfg=sw.Config(drain=True)), "drain")
        self.assertEqual(self.why(p, state={"brain_stopped": {"p": NOW - 60}}), "brain_stopped")
        self.assertEqual(self.why(p, state={"brain_stopped": {"p": NOW - 5 * 3600}}), "start_blocked")

    def test_loop_guard(self):
        r = sw.explain_idle(sw.Project(name="p", phase="planned"), [], {}, {"loop_guard": {"start|p": {"until": NOW + 3600, "n": 0}}},
                            sw.Config(), NOW, [])
        self.assertEqual(r["code"], "loop_guard")
        self.assertEqual(r["until"], NOW + 3600)

    def test_running_session_reasons(self):
        cfg = sw.Config(claude_idle="act")
        self.assertEqual(self.why(views=[_v(busy=True)], cfg=cfg), "working")
        self.assertEqual(self.why(views=[_v(last_assistant="bitti\nSTEWARD-ASK: ne?")], cfg=cfg), "session_asked")
        self.assertEqual(self.why(views=[_v(last_assistant="Sahip kararı bekliyor")], cfg=cfg), "owner_wait")
        self.assertEqual(self.why(views=[_v(last_activity=NOW - 60)], cfg=cfg), "idle_wait")
        self.assertEqual(self.why(views=[_v()], cfg=sw.Config(claude_idle="off")), "idle_off")
        self.assertEqual(self.why(views=[_v(last_assistant="tamam")], cfg=cfg), "no_next_work")
        p = sw.Project(name="p", phase="planned", cadence_minutes=60, notes="sıradaki: testleri yaz")
        self.assertEqual(self.why(p, views=[_v()], cfg=sw.Config(claude_idle="dry")), "idle_dry")
        self.assertEqual(self.why(p, views=[_v()], cfg=cfg), "nudging")
        st = {"claude_idle": {"p": {"at": NOW - 100, "n": 2, "mode": "act"}}}
        self.assertEqual(self.why(p, views=[_v(last_activity=NOW - 4000)], state=st, cfg=cfg), "nudge_exhausted")
        self.assertEqual(self.why(p, views=[_v(), _v("p20261101", blueprint="p")], cfg=cfg), "ambiguous")

    def test_matches_engine_nudge_decision(self):
        """explain_idle "nudging" dediğinde plan_claude_idle gerçekten dürtme üretiyor (aynı karar)."""
        p = sw.Project(name="p", phase="planned", cadence_minutes=60, notes="sıradaki: testleri yaz")
        cfg = sw.Config(claude_idle="act")
        acts, _ = sw.plan_claude_idle([_v()], {"p": p}, {}, cfg, NOW, [])
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])
        self.assertEqual(self.why(p, views=[_v()], cfg=cfg, actions=acts), "nudging")

    def test_all_and_lang(self):
        p = sw.Project(name="p", phase="paused")
        out = sw.explain_idle_all([], {"p": p}, {}, sw.Config(lang="en"), NOW, [])
        self.assertEqual(out["p"]["text"], "project is paused")


class ConfigAndLoopReset(_Tmp):
    def test_new_ui_keys(self):
        for key, val in (("claude_idle", "act"), ("keepwarm", "off"), ("wake_gate", "dry"), ("auto_start", "off"),
                         ("claude_idle_nudge_secs", 1800), ("ucli_idle_max_consecutive", 3), ("max_starts_total", 2)):
            r = ws.http_config({"key": key, "value": val})
            self.assertTrue(r["ok"], (key, r))
        cfg = ws.steward_config()
        self.assertEqual((cfg.claude_idle, cfg.keepwarm, cfg.auto_start, cfg.claude_idle_nudge_secs), ("act", "off", False, 1800))
        self.assertFalse(ws.http_config({"key": "claude_idle", "value": "maybe"})["ok"])
        self.assertFalse(ws.http_config({"key": "max_starts_total", "value": 99})["ok"])

    def test_loop_reset_human_only(self):
        st = {"loop_guard": {"start|a": {"n": 0, "first": 1.0, "until": 2e12}, "idle_nudge|b": {"n": 3, "first": 1.0}}}
        sw.save_state(st, "default")
        lst = ws.loop_guard_list("default")
        self.assertEqual([(x["key"], x["paused"]) for x in lst], [("idle_nudge|b", False), ("start|a", True)])
        self.assertFalse(ws.http_loop_reset({"actor": "brain"})["ok"])
        self.assertEqual(len(sw.load_state("default")["loop_guard"]), 2)
        self.assertFalse(ws.http_loop_reset({"key": "yok|x"})["ok"])
        self.assertEqual(ws.http_loop_reset({"key": "start|a"})["cleared"], ["start|a"])
        self.assertEqual(ws.http_loop_reset({})["cleared"], ["idle_nudge|b"])
        self.assertNotIn("loop_guard", sw.load_state("default"))


if __name__ == "__main__":
    unittest.main()

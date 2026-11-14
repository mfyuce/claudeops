"""`iş yok` kapatma (sahip 13 Kas): kural denetimleri, dry/act planı, muaflar, yeniden açılış tetikleyicileri. Canlı servis/tmux YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops import steward_nowork as snw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

NOW = 1_800_000_000.0
NONE = "Hepsi bitti.\nSTEWARD-NEXT: yok"


def view(name="p", txt=NONE, idle_min=45, **kw):
    base = dict(running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=1.0, last_activity=NOW - idle_min * 60,
                last_assistant=txt)
    base.update(kw)
    return sw.SessionView(name=name, **base)


def cfg(mode="dry", **kw):
    c = sw.Config(enabled=True, mode="act")
    c.no_work_close = mode
    for k, v in kw.items():
        setattr(c, k, v)
    return c


PROJ = {"p": sw.Project(name="p", phase="planned", cadence_minutes=0)}
CTX = {"open_q": set(), "answer_pending": {}, "review": {}, "jobs": set(), "errors": []}


def plan(views, state=None, c=None, ctx=None, projects=PROJ, open_work=lambda _p: 0):
    return snw.plan_no_work_close(views, projects, state or {}, c or cfg(), NOW, [], None, open_work=open_work, ctx=ctx or CTX)


class Check(unittest.TestCase):
    def res(self, v=None, ctx=None, open_work=lambda _p: 0, proj=PROJ["p"]):
        return snw.check_session(v or view(), proj, {}, cfg(), NOW, open_work, ctx or CTX)

    def test_closes_when_nothing_pending(self):
        r = self.res()
        self.assertTrue(r["close"], r)
        self.assertTrue(all(r["checks"].values()))

    def test_each_blocker(self):
        cases = {
            "no_work": dict(v=view(txt="Çalışıyorum.\nSTEWARD-NEXT: PE2 ölçüm betiği")),
            "idle": dict(v=view(idle_min=10)),
            "no_subagent": dict(v=view(subagent_active=True)),
            "no_question": dict(ctx=dict(CTX, open_q={"p"})),
        }
        for why, kw in cases.items():
            r = self.res(**kw)
            self.assertFalse(r["close"], why)
            self.assertEqual(r["why"], why)
        self.assertEqual(self.res(ctx=dict(CTX, answer_pending={"p": "q1"}))["why"], "no_question")     # iletilmemiş cevap
        self.assertEqual(self.res(v=view(txt="STEWARD-ASK: soru? öneri: a\nSTEWARD-NEXT: yok"))["why"], "no_question")   # oturum soru bıraktı
        self.assertEqual(self.res(v=view(txt="Sahipte, bekliyorum.\nSTEWARD-NEXT: yok"))["why"], "no_question")
        self.assertEqual(self.res(v=view(busy=True))["why"], "idle")
        self.assertEqual(self.res(v=view(subagent_unknown=True))["why"], "no_subagent")
        r = self.res(ctx=dict(CTX, review={"p": "bulgu:approved"}))                                       # review bulgusu
        self.assertEqual((r["close"], r["why"]), (False, "no_review_item:bulgu:approved"))
        self.assertEqual(self.res(ctx=dict(CTX, jobs={"p"}))["why"], "no_review_item")                    # açık varaka işi

    def test_open_todo_means_work_unless_session_says_none(self):
        self.assertFalse(self.res(v=view(txt="Devam ediyorum."), open_work=lambda _p: 3)["close"])      # TODO açık, oturum "yok" demedi
        self.assertFalse(self.res(open_work=lambda _p: 3)["close"])                                      # TBD#185: sahipsiz açık TODO varsa 'yok' dese de kapatma
        self.assertTrue(self.res(open_work=lambda _p: 0)["close"])


class Plan(unittest.TestCase):
    def test_dry_lists_and_records_report_without_ho_state(self):
        acts, st = plan([view()])
        self.assertEqual([a.kind for a in acts], ["idle_close"])
        a = acts[0]
        self.assertEqual((a.payload["marker"], a.payload["mode"], a.payload["pause_reason"]), ("no_work", "handover", "iş yok"))
        self.assertTrue(all(a.payload["checks"].values()))
        self.assertTrue(st["no_work_report"]["p"]["close"])
        self.assertNotIn("ho_pending", st)                                    # dry: devir kuyruğu YOK

    def test_act_queues_handover_close_pause_like_keepwarm_chain(self):
        acts, st = plan([view()], c=cfg("act"))
        self.assertEqual(st["ho_pending"]["p"], NOW)
        self.assertEqual((st["ho_close"]["p"], st["ho_pause"]["p"]), ("p", snw.NO_WORK_REASON))

    def test_report_covers_blocked_candidates_too(self):
        acts, st = plan([view(idle_min=5)])
        self.assertEqual(acts, [])
        self.assertEqual(st["no_work_report"]["p"]["why"], "idle")

    def test_off_and_drain_do_nothing(self):
        self.assertEqual(plan([view()], c=cfg("off")), ([], {}))
        self.assertEqual(plan([view()], c=cfg(drain=True))[0], [])

    def test_exempt_brain_manual_and_phases(self):
        self.assertEqual(plan([view("line")], projects={"line": sw.Project(name="line", phase="planned")})[0], [])
        self.assertEqual(plan([view("copsdev")], projects={"copsdev": sw.Project(name="copsdev", phase="planned")})[0], [])
        self.assertEqual(plan([view()], c=cfg(brain_name="p"))[0], [])
        for ph in ("paused", "done"):
            self.assertEqual(plan([view()], projects={"p": sw.Project(name="p", phase=ph)})[0], [], ph)
        self.assertEqual(plan([view(cli="codex")])[0], [])
        self.assertEqual(plan([view(tmux=False)])[0], [])
        self.assertEqual(plan([view(host="yuhem")])[0], [])

    def test_same_idle_period_decided_once(self):
        _, st = plan([view()])
        self.assertEqual(plan([view()], st)[0], [])

    def test_world_manual_class_skipped(self):
        class W:
            def own_projects(self, p):
                return p

            def session_class(self, name, bp):
                return "manual"
        self.assertEqual(snw.plan_no_work_close([view()], PROJ, {}, cfg(), NOW, [], W(), open_work=lambda _p: 0, ctx=CTX)[0], [])


class Reopen(unittest.TestCase):
    PAUSED = {"p": sw.Project(name="p", phase="paused")}

    def st(self, sha="a"):
        return {"no_work_paused": {"p": {"at": NOW - 100, "sha": sha}}}

    def test_triggers(self):
        r = snw.plan_no_work_reopen(self.PAUSED, self.st(), NOW, dict(CTX, answer_pending={"p": "q9"}))
        self.assertEqual((r[0].kind, r[0].payload["trigger"], r[0].payload["question_id"]), ("no_work_reopen", "answer", "q9"))
        r = snw.plan_no_work_reopen(self.PAUSED, self.st(), NOW, dict(CTX, review={"p": "bulgu:approved"}))
        self.assertTrue(r[0].payload["trigger"].startswith("review:"))
        r = snw.plan_no_work_reopen(self.PAUSED, self.st("a"), NOW, CTX, lambda _p: "b")
        self.assertEqual(r[0].payload["trigger"], "todo_changed")

    def test_no_trigger_no_reopen(self):
        self.assertEqual(snw.plan_no_work_reopen(self.PAUSED, self.st("a"), NOW, CTX, lambda _p: "a"), [])
        self.assertEqual(snw.plan_no_work_reopen(self.PAUSED, self.st("a"), NOW, CTX, lambda _p: ""), [])      # sha bilinmiyor
        # koşan review yalnız kapatmayı engeller, yeniden açmaz (14 Kas: hve koşu başladı diye 2 kez boşa açıldı)
        self.assertEqual(snw.plan_no_work_reopen(self.PAUSED, self.st("a"), NOW, dict(CTX, review={"p": snw.RUNNING_REVIEW}), lambda _p: "a"), [])
        self.assertEqual(snw.plan_no_work_reopen(PROJ, self.st(), NOW, dict(CTX, answer_pending={"p": "q"})), [])   # artık paused değil
        self.assertEqual(snw.plan_no_work_reopen(self.PAUSED, {}, NOW, dict(CTX, answer_pending={"p": "q"})), [])   # başka sebeple paused


class Apply(_Tmp):
    """paused -> planned + fresh bayrağı; direktif tetikleyicisi."""

    def test_directive_reopens_only_no_work_paused(self):
        sw.upsert_project("p", phase="paused", cadence_minutes=0)
        st = sw.load_state()
        st["no_work_paused"] = {"p": {"at": NOW, "sha": "a"}}
        sw.save_state(st)
        p = sw.load_projects()["p"]
        self.assertTrue(ws._no_work_directive_reopen(p, "default"))
        self.assertEqual(sw.load_projects()["p"].phase, "planned")
        self.assertNotIn("no_work_paused", sw.load_state())
        self.assertTrue(ws._consume_fresh_start("p", "default"))              # --new bayrağı bir kez
        self.assertFalse(ws._consume_fresh_start("p", "default"))
        self.assertIn("no_work_reopen", [e["event"] for e in sw.tail_log(20)])

    def test_manual_pause_is_not_reopened_by_directive(self):
        sw.upsert_project("q", phase="paused", cadence_minutes=0)
        self.assertFalse(ws._no_work_directive_reopen(sw.load_projects()["q"], "default"))
        self.assertEqual(sw.load_projects()["q"].phase, "paused")


if __name__ == "__main__":
    unittest.main()


class ChainStopIsExact(unittest.TestCase):
    """keepwarm/iş-yok zinciri durdurması TAM oturum adıyla (exact=True); sıradan stop eski imzayla (review cops 2 Kas)."""
    def test_pause_payload_stop_passes_exact(self):
        from unittest import mock
        from claudeops.commands import web_steward as ws
        from claudeops import steward as sw_
        calls = []
        with mock.patch.object(ws, "_act", lambda n, *a, **k: calls.append((n, a, k)) or {"ok": False}), \
                mock.patch.object(ws, "_target", lambda *a, **k: None):
            cfg = sw_.Config()
            ws._apply(sw_.Action("stop", "cli", "t", {"pause": {"project": "cli", "reason": "iş yok"}}), cfg, {})
            ws._apply(sw_.Action("stop", "cli", "t"), cfg, {})
        stops = [c for c in calls if c[0] == "stop"]
        self.assertEqual(stops[0][2].get("exact"), True)
        self.assertNotIn("exact", stops[1][2])

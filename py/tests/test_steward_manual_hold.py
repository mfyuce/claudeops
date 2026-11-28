"""L2 bayat izleme kaydı (28 Kas, hc 4 gün tur yok): kayıtlı ad kapalı + sahibin elle açtığı tek oturum 6 saattir çalışıyorsa
sahibe BİR KEZ sorulur; olumlu cevapta elle açılan oturum izlenir. Canlı servis YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from unittest import mock  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402

NOW = 1_800_000_000.0
H = sw.MANUAL_HOLD_ASK_SECONDS


def world(owned):
    return sw.world_for("default", sw.build_ownership_index({"default": ["hc", "x"]}), "degnekci", owned=owned)


class ManualHold(unittest.TestCase):
    def setUp(self):
        self.projects = {"hc": sw.Project(name="hc", phase="planned"), "x": sw.Project(name="x", phase="planned")}
        self.w = world({"hc": "hc", "x": "x"})
        self.views = [sw.SessionView(name="hc20261123", running=True, blueprint="hc")]

    def step(self, hold, questions=(), now=NOW, views=None, projects=None, w=None):
        return sw.manual_hold_step(hold, self.views if views is None else views, w or self.w, projects or self.projects,
                                   list(questions), now)

    def test_classifies_manual(self):
        self.assertEqual(self.w.session_class("hc20261123", "hc"), "manual")

    def test_starts_clock_then_asks_once_after_6h(self):
        hold, asks, res = self.step({})
        self.assertEqual(hold, {"hc": {"since": NOW, "session": "hc20261123"}})
        self.assertEqual((asks, res), ([], []))
        hold, asks, _ = self.step(hold, now=NOW + H - 1)
        self.assertEqual(asks, [])
        hold, asks, _ = self.step(hold, now=NOW + H)
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0]["session"], "hc20261123")
        self.assertIn("'hc20261123' izlensin mi", asks[0]["text"])
        hold, asks, _ = self.step(hold, now=NOW + 3 * H)
        self.assertEqual(asks, [])
        self.assertTrue(hold["hc"]["asked"])

    def test_no_clock_when_registered_runs_paused_or_two_manual(self):
        both = self.views + [sw.SessionView(name="hc", running=True)]
        self.assertEqual(self.step({}, views=both)[0], {})
        paused = {**self.projects, "hc": sw.Project(name="hc", phase="paused")}
        self.assertEqual(self.step({}, projects=paused)[0], {})
        two = self.views + [sw.SessionView(name="hc20261124", running=True, blueprint="hc")]
        self.assertEqual(self.step({}, views=two)[0], {})
        self.assertEqual(self.step({}, w=world({"hc": "", "x": "x"}))[0], {})     # kayıt "" = sahip açtı, sormadan bekler

    def test_session_change_restarts_clock(self):
        hold = {"hc": {"since": NOW - 2 * H, "session": "eski", "asked": True}}
        hold, asks, _ = self.step(hold)
        self.assertEqual(hold["hc"], {"since": NOW, "session": "hc20261123"})
        self.assertEqual(asks, [])

    def q(self, answer, qid="q1"):
        return sw.Question(qid, "hc", "soru", created_at=NOW, status="answered", answer=answer, answered_at=NOW,
                           source=sw.OWNED_ADOPT_SOURCE)

    def test_yes_adopts_no_closes(self):
        hold = {"hc": {"since": NOW - H, "session": "hc20261123", "asked": True}}
        h2, asks, res = self.step(hold, [self.q("evet")])
        self.assertEqual(res, [{"question_id": "q1", "project": "hc", "session": "hc20261123", "adopt": True}])
        self.assertEqual((h2, asks), ({}, []))
        h2, asks, res = self.step(hold, [self.q("hayır, beklesin")])
        self.assertFalse(res[0]["adopt"])
        self.assertTrue(h2["hc"]["asked"])      # yeniden sorulmaz
        self.assertEqual(asks, [])

    def test_yes_after_session_closed_does_not_adopt(self):
        hold = {"hc": {"since": NOW - H, "session": "hc20261123", "asked": True}}
        _, _, res = self.step(hold, [self.q("evet")], views=[])
        self.assertEqual(res, [{"question_id": "q1", "project": "hc", "session": "hc20261123", "adopt": False}])

    def test_other_sources_and_delivered_ignored(self):
        q = self.q("evet")
        q.source = "hc"
        delivered = self.q("evet", "q2")
        delivered.delivered_at = NOW
        self.assertEqual(self.step({}, [q, delivered])[2], [])


class Apply(_Tmp):
    """Uygulayıcı: süre kaydı state'e, soru `owned_adopt` kaynaklı ve sahibe bildirilir; 'evet' -> owned + teslim edildi."""

    def test_ask_then_yes_adopts(self):
        sw.save_projects({"hc": sw.Project(name="hc", phase="planned")})
        sw.save_state({"owned": {"hc": "hc"}})
        paths, cfg = sw.paths_for("default"), sw.Config()
        views = [sw.SessionView(name="hc20261123", running=True, blueprint="hc")]
        sent = []
        with mock.patch.object(ws, "_notify", lambda c, t: sent.append(t) or True):
            w = ws._world("default")
            self.assertEqual(w.session_class("hc20261123", "hc"), "manual")
            ws._maintain_manual_hold(views, sw.load_projects(), w, paths, "default", NOW, cfg)
            self.assertEqual(sw.load_state()["manual_hold"]["hc"]["since"], NOW)
            ws._maintain_manual_hold(views, sw.load_projects(), w, paths, "default", NOW + H, cfg)
            ws._maintain_manual_hold(views, sw.load_projects(), w, paths, "default", NOW + H + 60, cfg)
        qs = [q for q in sw.load_questions() if q.source == sw.OWNED_ADOPT_SOURCE]
        self.assertEqual(len(qs), 1)
        self.assertEqual(len(sent), 1)
        sw.answer_question(qs[0].id, "evet")
        w2 = ws._maintain_manual_hold(views, sw.load_projects(), w, paths, "default", NOW + H + 120, cfg)
        self.assertEqual(w2.owned["hc"], "hc20261123")
        self.assertEqual(sw.load_state()["owned"]["hc"], "hc20261123")
        self.assertEqual(w2.session_class("hc20261123", "hc"), "own")
        self.assertTrue(next(q for q in sw.load_questions() if q.id == qs[0].id).delivered_at)
        self.assertNotIn("hc", sw.load_state().get("manual_hold") or {})


if __name__ == "__main__":
    unittest.main()

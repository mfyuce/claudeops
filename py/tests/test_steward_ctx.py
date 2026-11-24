"""Değnekçi testleri (test_steward.py bölünmüş parça: ctx_a). Çalıştırma: python3 -m pytest py/tests/test_steward_ctx.py"""
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings, steward as sw, steward_jobs as sj  # noqa: E402
from claudeops.commands import mcp_queue, mcp_steward, web_steward  # noqa: E402
from claudeops.providers import get_provider  # noqa: E402
from claudeops.providers.base import CliProvider, OneshotError  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402

def _view(name, **kw):
    base = dict(running=True, cwd="/tmp/x", cli="claude", busy=False, history_size=100, tmux=True,
                started_at=1000.0, last_activity=1000.0)
    base.update(kw)
    return sw.SessionView(name=name, **base)

def steward_cfg(**kw):
    """settings'ten okunan etkin ayar (kart/motor testleri için `_cfg`'in canlı-ayar karşılığı)."""
    return settings.steward_config()

def _cfg(**kw):
    c = sw.Config(enabled=True)
    c.done_handover = False        # eski testler DONE -> doğrudan stop'u sınar; devirli yol ayrı sınıfta (DoneHandoverTest)
    for k, v in kw.items():
        setattr(c, k, v)
    return c

def _git(cwd, *args):
    subprocess.run(["git", "-C", cwd, "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True, text=True)

def _make_repo(path, **docs):
    os.makedirs(path, exist_ok=True)
    _git(path, "init", "-q")
    for fn, body in docs.items():
        with open(os.path.join(path, fn), "w", encoding="utf-8") as f:
            f.write(body)
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "ilk commit")
    return path

GOOD_JSON = json.dumps({"goal": "Bir kitap yaz", "phase_guess": "planned", "next_step": "3. bölümü bitir",
                        "open_tbds": ["TBD#1 kapak?"], "blockers": [], "recent_done": ["2. bölüm"]})


class ContextQuestionTest(unittest.TestCase):
    """'Bu oturumda mı sürdüreyim, devirle mi' sorusu bağlam ölçümünden motor tarafından cevaplanır."""
    Q = "§3.16.15 entegrasyon zincirini bu oturumda mı sürdüreyim, yoksa devir notuyla yeni oturuma mı bırakayım?"

    def setUp(self):
        self.now = 100000.0
        self.projects = {"a": sw.Project(name="a", phase="planned", priority=1, cadence_minutes=60)}

    def _q(self, text=None, source="a"):
        return sw.Question(id="q1", project="a", text=text or self.Q, created_at=self.now - 60, source=source)

    def _plan(self, tokens, text=None, **cfgkw):
        cfg = _cfg(context_warn_tokens=300000, **cfgkw)
        v = _view("a", context_tokens=tokens, model="claude-sonnet-5-5")
        return sw.plan_tick([v], self.projects, {}, cfg, self.now, [self._q(text)], [])

    def test_classifier(self):
        self.assertTrue(sw.is_context_question(self.Q))
        self.assertFalse(sw.is_context_question("Bu oturumda commit+push yapayım mı, devir notunda mı yazayım?"))
        self.assertFalse(sw.is_context_question("Sonnet doğrulama turunu şimdi koşayım mı?"))

    def test_low_context_continues_without_handover(self):
        acts, st = self._plan(100000)
        kinds = [a.kind for a in acts if a.name == "a"]
        self.assertIn("auto_answer", kinds)
        self.assertNotIn("handover", kinds)
        ans = next(a for a in acts if a.kind == "auto_answer")
        self.assertFalse(ans.payload["handover"])
        self.assertIn("Bu oturumda sürdür", ans.payload["answer"])
        self.assertIn("100K/300K", ans.payload["answer"])

    def test_high_context_hands_over(self):
        acts, st = self._plan(240000)   # 0.8 >= 0.7 (eşik 300K'nın altında, otomatik devir henüz tetiklemez)
        kinds = [a.kind for a in acts if a.name == "a"]
        self.assertEqual(kinds.count("handover"), 1)
        ans = next(a for a in acts if a.kind == "auto_answer")
        self.assertTrue(ans.payload["handover"])
        self.assertIn("Önce devir", ans.payload["answer"])
        self.assertIn("a", st["ho_pending"])

    def test_unknown_context_or_disabled_leaves_question(self):
        acts, _ = self._plan(None)
        self.assertNotIn("auto_answer", [a.kind for a in acts])
        acts, _ = self._plan(240000, auto_context_answer=False)
        self.assertNotIn("auto_answer", [a.kind for a in acts])

    def test_over_threshold_single_handover(self):
        acts, _ = self._plan(310000)   # eşik aşıldı: mevcut devir yolu, ikinci handover üretilmez
        self.assertEqual([a.kind for a in acts if a.name == "a"].count("handover"), 1)


class PausedProjectNoContextHandoverTest(unittest.TestCase):
    """Canlı döngü (6 Kas 23:4x, cops20261106 318K): paused projede eşik devri -> READY -> ho_halted -> sonraki tick yine devir.
    Paused/done projede otomatik bağlam devri HİÇ gönderilmez; planned projede eşik aynen çalışır."""

    def setUp(self):
        self.now = 100000.0
        self.cfg = _cfg(context_warn_tokens=300000)

    def _tick(self, phase, tokens=318000, state=None, qs=()):
        projects = {"a": sw.Project(name="a", phase=phase, priority=1, cadence_minutes=60)}
        v = _view("a", context_tokens=tokens, model="claude-sonnet-5-5")
        return sw.plan_tick([v], projects, dict(state or {}), self.cfg, self.now, list(qs), [])

    def test_paused_over_threshold_sends_no_handover_on_any_tick(self):
        st = {}
        for _ in range(3):
            acts, st = self._tick("paused", state=st)
            self.assertNotIn("handover", [a.kind for a in acts])
            self.assertNotIn("a", st.get("ho_pending") or {})
            self.now += 300

    def test_done_project_also_gets_no_threshold_handover(self):
        acts, _ = self._tick("done")
        self.assertNotIn("handover", [a.kind for a in acts])

    def test_planned_project_still_hands_over_at_threshold(self):
        acts, st = self._tick("planned")
        self.assertEqual([a.kind for a in acts if a.name == "a"].count("handover"), 1)
        self.assertIn("a", st["ho_pending"])

    def test_context_question_on_paused_project_does_not_start_a_handover(self):
        q = sw.Question(id="q1", project="a", text=ContextQuestionTest.Q, created_at=self.now - 60, source="a")
        acts, st = self._tick("paused", tokens=240000, qs=[q])
        self.assertNotIn("handover", [a.kind for a in acts])
        self.assertNotIn("auto_answer", [a.kind for a in acts])


class HandoverDeferTest(unittest.TestCase):
    """Eşik devri oturum meşgul / alt ajanı çalışıyor / alt ajan durumu bilinmiyorken ertelenir; sert tavanda zorlanır."""

    def setUp(self):
        self.now = 100000.0
        self.projects = {"a": sw.Project(name="a", phase="planned", cadence_minutes=60)}
        self.cfg = _cfg(max_active=4, context_warn_tokens=300000, context_warn_tokens_fable=0)

    def _tick(self, views, state=None, now=None, qs=None, cfg=None):
        return sw.plan_tick(views, self.projects, state or {}, cfg or self.cfg, now or self.now, qs or [], [])

    @staticmethod
    def _of(acts, name, kind=None):
        return [x for x in acts if x.name == name and (kind is None or x.kind == kind)]

    def test_pure_decision(self):
        v = _view("a", busy=False)
        self.assertEqual(sw.handover_defer_decision(v, self.cfg, self.now, None, 310000, 300000), ("go", ""))
        v = _view("a", busy=None, subagent_active=True)
        self.assertEqual(sw.handover_defer_decision(v, self.cfg, self.now, None, 310000, 300000)[0], "defer")
        self.assertEqual(sw.handover_defer_decision(v, self.cfg, self.now, None, 390000, 300000)[0], "force")
        self.assertEqual(sw.handover_defer_decision(v, self.cfg, self.now, self.now - 29 * 60, 310000, 300000)[0], "defer")
        self.assertEqual(sw.handover_defer_decision(v, self.cfg, self.now, self.now - 30 * 60, 310000, 300000)[0], "force")
        off = _cfg(handover_defer_max_minutes=0)
        self.assertEqual(sw.handover_defer_decision(v, off, self.now, None, 310000, 300000)[0], "go")
        noratio = _cfg(handover_force_ratio=0.0)
        self.assertEqual(sw.handover_defer_decision(v, noratio, self.now, None, 900000, 300000)[0], "defer")
        self.assertEqual((sw.Config().handover_force_ratio, sw.Config().handover_defer_max_minutes), (1.3, 30))

    def test_subagent_active_defers_then_hands_over_when_quiet(self):
        v = _view("a", context_tokens=320000, subagent_active=True)
        acts, st = self._tick([v])
        self.assertEqual(self._of(acts, "a", "handover"), [])
        rec = self._of(acts, "a", "handover_deferred")
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0].reason, "subagent_active")
        self.assertIn("token", rec[0].payload["handover_reason"])
        self.assertEqual(st["ho_deferred"]["a"]["since"], self.now)
        self.assertNotIn("a", st["ho_pending"])
        # sonraki tick: hâlâ çalışıyor -> devir yok, kayıt tekrar yazılmaz, başlangıç korunur
        acts, st = self._tick([v], st, self.now + 120)
        self.assertEqual(self._of(acts, "a"), [])
        self.assertEqual(st["ho_deferred"]["a"]["since"], self.now)
        # alt ajan sustu, meşgul değil -> ilk tick'te devir
        quiet = _view("a", context_tokens=320000, subagent_active=False, busy=False)
        acts, st = self._tick([quiet], st, self.now + 240)
        ho = self._of(acts, "a", "handover")
        self.assertEqual(len(ho), 1)
        self.assertIn("ertelenmişti", ho[0].reason)
        self.assertNotIn("ho_deferred", st)
        self.assertIn("a", st["ho_pending"])

    def test_busy_and_unknown_defer(self):
        for kw, why in (({"busy": True}, "busy"), ({"subagent_unknown": True}, "subagent_unknown"),
                        ({"busy": True, "subagent_active": True}, "busy,subagent_active")):
            acts, st = self._tick([_view("a", context_tokens=320000, **kw)])
            self.assertEqual(self._of(acts, "a", "handover"), [], kw)
            self.assertEqual([x.reason for x in self._of(acts, "a", "handover_deferred")], [why])
            self.assertIn("a", st["ho_deferred"])
        # busy None (sinyal yok) meşgul sayılmaz
        acts, _ = self._tick([_view("a", context_tokens=320000, busy=None)])
        self.assertEqual(len(self._of(acts, "a", "handover")), 1)

    def test_history_fallback_defers_too(self):
        v = _view("a", busy=True, history_size=1990, context_tokens=None, started_at=self.now - 3600)
        acts, st = self._tick([v])
        self.assertEqual(self._of(acts, "a", "handover"), [])
        self.assertIn("history_size", self._of(acts, "a", "handover_deferred")[0].payload["handover_reason"])

    def test_force_by_ratio(self):
        acts, st = self._tick([_view("a", context_tokens=390000, subagent_active=True)])
        self.assertEqual(len(self._of(acts, "a", "handover")), 1)
        self.assertEqual(self._of(acts, "a", "handover_deferred"), [])
        self.assertNotIn("ho_deferred", st)
        # ertelenmiş kayıt varken oran aşılırsa gerekçe zorlamayı söyler
        acts, _ = self._tick([_view("a", context_tokens=390000, subagent_active=True)],
                             {"ho_deferred": {"a": {"since": self.now - 60, "why": "subagent_active"}}})
        self.assertIn("zorla", self._of(acts, "a", "handover")[0].reason)

    def test_force_by_time(self):
        v = _view("a", context_tokens=320000, subagent_unknown=True)
        st0 = {"ho_deferred": {"a": {"since": self.now - 29 * 60, "why": "subagent_unknown"}}}
        acts, st = self._tick([v], st0)
        self.assertEqual(self._of(acts, "a"), [])      # neden aynı: yeni kayıt yok, devir yok
        acts, st = self._tick([v], st, self.now + 60)
        ho = self._of(acts, "a", "handover")
        self.assertEqual(len(ho), 1)
        self.assertIn("zorla", ho[0].reason)
        self.assertIn("30", ho[0].reason)
        self.assertNotIn("ho_deferred", st)

    def test_defer_disabled_keeps_old_behaviour(self):
        cfg = _cfg(max_active=4, context_warn_tokens=300000, handover_defer_max_minutes=0)
        acts, st = self._tick([_view("a", context_tokens=320000, subagent_active=True)], cfg=cfg)
        self.assertEqual(len(self._of(acts, "a", "handover")), 1)
        self.assertNotIn("ho_deferred", st)

    def test_below_threshold_drops_deferral(self):
        st0 = {"ho_deferred": {"a": {"since": self.now - 60, "why": "busy"}}}
        acts, st = self._tick([_view("a", context_tokens=100000, busy=True)], st0)
        self.assertEqual(self._of(acts, "a"), [])
        self.assertNotIn("ho_deferred", st)

    def test_brain_same_rule(self):
        brain = _view("degnekci", context_tokens=320000, subagent_active=True)
        acts, st = self._tick([brain])
        self.assertEqual(self._of(acts, "degnekci", "handover"), [])
        self.assertEqual(len(self._of(acts, "degnekci", "handover_deferred")), 1)
        acts, st = self._tick([_view("degnekci", context_tokens=320000)], st, self.now + 120)
        self.assertEqual(len(self._of(acts, "degnekci", "handover")), 1)
        acts, _ = self._tick([_view("degnekci", context_tokens=320000, busy=True)],
                             {"ho_deferred": {"degnekci": {"since": self.now - 31 * 60, "why": "busy"}}})
        self.assertEqual(len(self._of(acts, "degnekci", "handover")), 1)

    def test_no_second_action_while_deferred(self):
        q = sw.Question(id="q1", project="a", text="soru?", created_at=1.0, status="answered", answer="evet",
                        answered_at=2.0, source="a")
        v = _view("a", context_tokens=320000, subagent_unknown=True, last_assistant="")
        acts, _ = self._tick([v], qs=[q])
        self.assertEqual([x.kind for x in self._of(acts, "a")], ["handover_deferred"])
        # erteleme yokken (eşik altı) aynı cevap iletilirdi
        acts, _ = self._tick([_view("a", context_tokens=100000, subagent_unknown=True, last_assistant="")], qs=[q])
        self.assertEqual([x.kind for x in self._of(acts, "a")], ["deliver_answer"])

    def test_context_question_path_defers(self):
        q = sw.Question(id="q1", project="a", text=ContextQuestionTest.Q, created_at=self.now - 60, source="a")
        v = _view("a", context_tokens=240000, model="claude-sonnet-5-5", subagent_active=True)
        acts, st = self._tick([v], qs=[q])
        self.assertEqual([x.kind for x in self._of(acts, "a")], ["handover_deferred"])   # cevap da devir de yok
        self.assertIn("context soru", self._of(acts, "a")[0].payload["handover_reason"])
        quiet = _view("a", context_tokens=240000, model="claude-sonnet-5-5")
        acts, st = self._tick([quiet], st, self.now + 120, qs=[q])
        self.assertEqual([x.kind for x in self._of(acts, "a")], ["auto_answer", "handover"])
        self.assertTrue(self._of(acts, "a", "auto_answer")[0].payload["handover"])
        # düşük bağlam: "sürdür" cevabı ertelenmez (devir yok)
        low = _view("a", context_tokens=100000, model="claude-sonnet-5-5", subagent_active=True)
        acts, _ = self._tick([low], qs=[q])
        self.assertEqual([x.kind for x in self._of(acts, "a")], ["auto_answer"])

    def test_engine_logs_deferral(self):
        cfg = _cfg(sid="default")
        logged = []
        with mock.patch.object(sw, "log_event", lambda ev, **kw: logged.append((ev, kw))):
            res = web_steward._apply(sw.Action("handover_deferred", "a", "busy", {"handover_reason": "context x"}), cfg, {})
        self.assertTrue(res["ok"])
        self.assertEqual(logged[0][0], "handover_deferred")
        self.assertEqual((logged[0][1]["name"], logged[0][1]["reason"], logged[0][1]["handover"]), ("a", "busy", "context x"))


if __name__ == "__main__":
    unittest.main()

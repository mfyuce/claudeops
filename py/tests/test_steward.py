"""Değnekçi (steward) — çekirdek kurallar, depo, prompt'lar, ayar okuması, MCP araç adaptörü, HTTP katmanı
(stdlib unittest, canlı tmux/CLI YOK).

Çalıştırma:  python3 py/tests/test_steward.py -v
`CLAUDEOPS_DIR` geçici bir klasöre yönlendirilir (modül sabitleri patch'lenir), gerçek ayar/roster'a dokunmaz.
"""
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
from claudeops import settings, steward as sw  # noqa: E402
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
    for k, v in kw.items():
        setattr(c, k, v)
    return c


class StoreTest(_Tmp):
    def test_project_roundtrip_and_validation(self):
        p = sw.upsert_project("kitap", phase="planning", kind="book", goal="bir kitap", priority=9, cadence_minutes=-5)
        self.assertEqual((p.phase, p.kind, p.priority, p.cadence_minutes), ("planning", "book", 5, 0))
        sw.upsert_project("kitap", phase="bogus", notes="n")   # geçersiz faz yok sayılır, not yazılır
        again = sw.load_projects()["kitap"]
        self.assertEqual((again.phase, again.notes, again.goal), ("planning", "n", "bir kitap"))
        with self.assertRaises(ValueError):
            sw.upsert_project("Bad Name")
        self.assertTrue(sw.remove_project("kitap"))
        self.assertEqual(sw.load_projects(), {})

    def test_questions_dedup_answer_deliver(self):
        q1 = sw.add_question("p", "A mı B mi?", source="s")
        q2 = sw.add_question("p", "A mı B mi?")
        self.assertEqual(q1.id, q2.id)
        self.assertEqual(len(sw.open_questions()), 1)
        self.assertIsNone(sw.answer_question("yok", "x"))
        a = sw.answer_question(q1.id, "A")
        self.assertEqual((a.status, a.answer), ("answered", "A"))
        self.assertEqual([q.id for q in sw.undelivered_answers()], [q1.id])
        sw.mark_delivered(q1.id)
        self.assertEqual(sw.undelivered_answers(), [])

    def test_ideas_and_log(self):
        i = sw.add_idea("fikir", source="cli")
        self.assertEqual(sw.update_idea(i.id, status="project", project="yeni").project, "yeni")
        self.assertIsNone(sw.update_idea("yok", status="dropped"))
        sw.log_event("x", a=1)
        self.assertEqual(sw.tail_log(5)[-1]["a"], 1)

    def test_persona_override_and_bundled(self):
        self.assertIn("değnekçi", sw.persona_text("").lower())
        self.assertEqual(sw.persona_text("  özel  "), "özel\n")


class MarkerTest(unittest.TestCase):
    def test_scan_markers_ignores_writing_examples(self):
        txt = ("Protokol:\n- takıldın: `STEWARD-BLOCKED: <nerede takıldın>`\n> STEWARD-ASK: alıntı soru?\n"
               "```\nSTEWARD-ASK: kod bloğundaki soru?\nSTEWARD-IDEA: kod fikri\n```\n"
               "Takıldım: STEWARD-BLOCKED: <kullanıcı aksiyonu>`...\n")
        m = sw.scan_markers(txt)
        self.assertEqual((m["asks"], m["blocked"], m["ideas"]), ([], [], []))
        m = sw.scan_markers("```\nx\n```\nSTEWARD-ASK: gerçek soru mu?\n- `STEWARD-IDEA: gerçek fikir`\n")
        self.assertEqual((m["asks"], m["ideas"]), (["gerçek soru mu?"], ["gerçek fikir"]))

    def test_scan_markers_job_line(self):
        m = sw.scan_markers("bitti\n- STEWARD-JOB: import_registry REQUEST_x.md Cezîrî dipnotları\n")
        self.assertEqual(m["jobs"], ["import_registry REQUEST_x.md Cezîrî dipnotları"])
        acts = sw.marker_record_actions("wifi5gppr", "wifi5gppr", m)
        self.assertEqual([(a.kind, a.reason) for a in acts], [("ask_user", "STEWARD-JOB")])
        self.assertTrue(acts[0].payload["routine"])   # beyin turunda rutin madde: telefona gitmez
        self.assertTrue(acts[0].payload["text"].startswith(sw.JOB_REQUEST_PREFIX))
        self.assertEqual(sw.scan_markers("STEWARD-JOB:\n")["jobs"], [])
        # düzyazıdaki anma, yer tutucu ve protokol metninin yankısı iş isteği SAYILMAZ
        for txt in ("Yazdığımda `STEWARD-JOB:` satırını görecek, bunu izlerim.",
                    "- `STEWARD-JOB: <iş türü> <dosya yolu> [kısa açıklama]`; değnekçi gönderir",
                    "STEWARD-JOB: ` yazısı iş isteği sanıldı", "Cevabım: STEWARD-JOB: embed x.md"):
            self.assertEqual(sw.scan_markers(txt)["jobs"], [], txt)
        self.assertEqual(sw.scan_markers("`STEWARD-JOB: embed a.md`")["jobs"], ["embed a.md"])
        self.assertIn(sw.MARK_JOB, sw._PROTOCOL_TR)
        self.assertIn(sw.MARK_JOB, sw._PROTOCOL_EN)

    def test_scan_markers(self):
        text = ("iş bitti.\n- STEWARD-ASK: A mı B mi?\nSTEWARD-IDEA: `yeni şey`\n"
                "   * STEWARD-BLOCKED: build kırık\nSTEWARD-PLAN-READY\n")
        m = sw.scan_markers(text)
        self.assertEqual(m["asks"], ["A mı B mi?"])
        self.assertEqual(m["ideas"], ["yeni şey"])
        self.assertEqual(m["blocked"], ["build kırık"])
        self.assertTrue(m["plan_ready"])
        self.assertFalse(m["done"])
        self.assertTrue(sw.scan_markers("x\nSTEWARD-DONE\n")["done"])
        self.assertFalse(sw.scan_markers("COPS-STEWARD-END STEWARD-DONE")["done"])
        self.assertEqual(sw.scan_markers("")["asks"], [])


class PromptTest(unittest.TestCase):
    def test_directive_by_phase_and_answer(self):
        p = sw.Project(name="p", phase="planning", goal="kitap", notes="sıradaki: giriş")
        t = sw.build_directive(p)
        self.assertIn("Planlama fazındayız", t)
        self.assertIn(sw.MARK_PLAN_READY, t)
        self.assertIn("sıradaki: giriş", t)
        self.assertIn(sw.MARK_ASK, t)
        p.phase = "planned"
        self.assertIn(sw.MARK_DONE, sw.build_directive(p, lang="en"))
        q = sw.Question(id="q1", project="p", text="A mı B mi?", created_at=0, status="answered", answer="A")
        t = sw.build_directive(p, extra="devam", answer=q)
        self.assertIn("Cevabım: A", t)
        self.assertIn("devam", t)
        self.assertNotIn("Plan hazır, uygulama", t)   # extra şablonun yerine geçer

    def test_tour_prompt_lists_items_and_end_marker(self):
        items = [{"kind": "idle", "name": "p", "phase": "planned", "goal": "g", "idle_minutes": 12,
                  "last_exchange": {"user": "u", "assistant": "a"}, "docs": {"TODO.md": "- x"}},
                 {"kind": "idea", "id": "i1", "text": "fikir"}]
        qs = [sw.Question(id="q9", project="p", text="soru", created_at=0)]
        t = sw.build_tour_prompt(items, lang="tr", open_qs=qs, now=0)
        for needle in ("BOŞTA — p", "boşta: 12 dk", "FİKİR", "id=i1", "[q9]", sw.MARK_END, "TODO.md"):
            self.assertIn(needle, t)
        self.assertIn("IDLE — p", sw.build_tour_prompt(items, lang="en"))

    def test_workspace_claude_md(self):
        md = sw.build_workspace_claude_md("PERSONA")
        self.assertTrue(md.startswith("PERSONA"))
        self.assertIn("steward_directive", md)
        self.assertIn(sw.MARK_END, md)


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


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.now = 100000.0
        self.projects = {"a": sw.Project(name="a", phase="planned", priority=1, cadence_minutes=60),
                         "b": sw.Project(name="b", phase="planning", priority=2, cadence_minutes=60),
                         "c": sw.Project(name="c", phase="paused")}

    def test_handover_then_respawn(self):
        cfg = _cfg(history_warn_at=1900)
        v = _view("a", history_size=1950)
        acts, st = sw.plan_tick([v], self.projects, {}, cfg, self.now, [], [])
        self.assertEqual([a.kind for a in acts if a.name == "a"], ["handover"])
        self.assertIn("a", st["ho_pending"])
        # ikinci tick: hâlâ meşgul → bekle
        v.busy = True
        acts, st = sw.plan_tick([v], self.projects, st, cfg, self.now + 60, [], [])
        self.assertEqual([a.kind for a in acts if a.name == "a"], [])
        # READY FOR HANDOVER + boşta → respawn
        v.busy, v.last_assistant = False, "... READY FOR HANDOVER özet"
        acts, st = sw.plan_tick([v], self.projects, st, cfg, self.now + 120, [], [])
        self.assertEqual([a.kind for a in acts if a.name == "a"], ["respawn"])
        self.assertNotIn("a", st["ho_pending"])

    def test_handover_grace_expiry_and_gone_session(self):
        cfg = _cfg(ho_grace_minutes=10)
        st = {"ho_pending": {"a": self.now - 11 * 60}}
        acts, _ = sw.plan_tick([_view("a", busy=None)], self.projects, st, cfg, self.now, [], [])
        self.assertEqual([a.kind for a in acts if a.name == "a"], ["respawn"])
        acts, _ = sw.plan_tick([_view("a", running=False)], self.projects, st, cfg, self.now, [], [])
        self.assertEqual([a.kind for a in acts if a.name == "a"], ["respawn"])

    def test_markers_once_per_reply(self):
        cfg = _cfg()
        v = _view("b", last_assistant="STEWARD-ASK: hangisi?\nSTEWARD-IDEA: x\nSTEWARD-PLAN-READY")
        acts, st = sw.plan_tick([v], self.projects, {}, cfg, self.now, [], [])
        kinds = sorted(a.kind for a in acts if a.name == "b")
        self.assertEqual(kinds, ["ask_user", "idea", "set_phase"])
        self.assertEqual(next(a for a in acts if a.kind == "set_phase").payload["phase"], "planned")
        acts, _ = sw.plan_tick([v], self.projects, st, cfg, self.now + 1, [], [])
        self.assertEqual([a for a in acts if a.name == "b"], [])   # aynı yanıt yeniden işlenmez

    def test_done_marker_stops_session(self):
        acts, _ = sw.plan_tick([_view("a", last_assistant="STEWARD-DONE")], self.projects, {}, _cfg(), self.now, [], [])
        self.assertEqual(sorted(a.kind for a in acts if a.name == "a"), ["set_phase", "stop"])

    def test_done_marker_ignored_when_project_notes_have_no_done_tag(self):
        self.projects["a"].notes = "sürekli geliştirme " + sw.NO_DONE_TAG
        acts, _ = sw.plan_tick([_view("a", last_assistant="STEWARD-DONE")], self.projects, {}, _cfg(), self.now, [], [])
        self.assertEqual([a for a in acts if a.name == "a" and a.kind in ("set_phase", "stop")], [])
        self.assertTrue(sw.done_blocked(self.projects["a"]))

    def test_due_projects_respect_slots_priority_and_cadence(self):
        cfg = _cfg(max_active=2, max_starts_per_tick=5)
        acts, st = sw.plan_tick([], self.projects, {}, cfg, self.now, [], [])
        self.assertEqual([(a.kind, a.name) for a in acts], [("start", "a"), ("start", "b")])
        # a çalışıyor, b yeni uğranmış → sırası gelmemiş, c paused → hiçbir start yok
        self.projects["b"].last_visit = self.now - 10 * 60
        acts, _ = sw.plan_tick([_view("a", busy=True)], self.projects, {}, cfg, self.now, [], [])
        self.assertEqual([a.kind for a in acts], [])
        # max_starts_per_tick=1 → yalnız en öncelikli
        self.projects["b"].last_visit = 0
        acts, _ = sw.plan_tick([], self.projects, {}, _cfg(max_active=4, max_starts_per_tick=1), self.now, [], [])
        self.assertEqual([a.name for a in acts], ["a"])

    def test_drain_starts_nothing_but_keeps_answers_and_running(self):
        cfg = _cfg(max_active=4, max_starts_per_tick=5, drain=True)
        acts, _ = sw.plan_tick([], self.projects, {}, cfg, self.now, [], [])
        self.assertEqual([a for a in acts if a.kind == "start"], [])
        acts, _ = sw.plan_tick([_view("b", last_assistant="STEWARD-DONE")], self.projects, {}, cfg, self.now, [], [])
        self.assertEqual(sorted(a.kind for a in acts if a.name == "b"), ["set_phase", "stop"])   # işaretler hâlâ işlenir

    def test_slot_pressure_stops_idle_session(self):
        cfg = _cfg(max_active=1, stop_idle_minutes=30, idle_minutes=5)
        idle = _view("a", busy=False, last_activity=self.now - 40 * 60, started_at=self.now - 3600)
        acts, _ = sw.plan_tick([idle], self.projects, {}, cfg, self.now, [], [])
        self.assertEqual([(a.kind, a.name) for a in acts], [("stop", "a")])
        # boşta ama yeni → durdurma yok, tur maddesi olur (beyin yoksa tur yok)
        fresh = _view("a", busy=False, last_activity=self.now - 6 * 60, started_at=self.now - 3600)
        acts, st = sw.plan_tick([fresh], self.projects, {}, cfg, self.now, [], [])
        self.assertEqual(acts, [])
        self.assertEqual(st["pending_items"], 1)

    def test_answer_delivery_running_busy_or_stopped(self):
        cfg = _cfg(max_active=4)
        q = sw.Question(id="q", project="a", text="?", created_at=0, status="answered", answer="A", answered_at=1)
        acts, st = sw.plan_tick([_view("a", busy=False)], self.projects, {}, cfg, self.now, [q], [])
        self.assertEqual([(a.kind, a.payload.get("question_id")) for a in acts if a.name == "a"], [("deliver_answer", "q")])
        acts, _ = sw.plan_tick([_view("a", busy=True)], self.projects, {}, cfg, self.now, [q], [])
        self.assertEqual([a.kind for a in acts if a.name == "a"], [])
        acts, _ = sw.plan_tick([_view("a", running=False)], self.projects, {}, cfg, self.now, [q], [])
        self.assertEqual([(a.kind, a.payload.get("question_id")) for a in acts if a.name == "a"], [("start", "q")])

    def test_adhoc_session_answer_goes_to_asking_session_only_if_running(self):
        cfg = _cfg(max_active=4)
        q = sw.Question(id="q", project="zk_x20261020", text="?", created_at=0, status="answered", answer="A",
                        answered_at=1, source="zk_x20261020")
        sess = _view("zk_x20261020", busy=False)
        acts, _ = sw.plan_tick([sess], self.projects, {}, cfg, self.now, [q], [])
        self.assertEqual([(a.kind, a.name) for a in acts if a.kind == "deliver_answer"], [("deliver_answer", "zk_x20261020")])
        acts, _ = sw.plan_tick([_view("zk_x20261020", busy=True)], self.projects, {}, cfg, self.now, [q], [])
        self.assertEqual([a.kind for a in acts if a.kind == "deliver_answer"], [])      # meşgul: sonraki tick
        acts, _ = sw.plan_tick([_view("zk_x20261020", running=False)], self.projects, {}, cfg, self.now, [q], [])
        self.assertEqual([a.kind for a in acts if a.name == "zk_x20261020"], [])   # kapalıysa açılmaz

    def test_instance_sessions_map_to_blueprint_project(self):
        cfg = _cfg(max_active=1)
        inst = _view("a20261019", blueprint="a", busy=True)
        acts, _ = sw.plan_tick([inst], self.projects, {}, cfg, self.now, [], [])
        self.assertEqual([a.kind for a in acts], [])   # a zaten çalışıyor (instance), slot dolu → b başlamaz

    def test_tour_only_when_brain_idle_and_due(self):
        cfg = _cfg(idle_minutes=5, tour_minutes=15)
        self.projects = {"a": self.projects["a"]}
        idle = _view("a", busy=False, last_activity=self.now - 10 * 60)
        brain = _view("degnekci", busy=True)
        acts, st = sw.plan_tick([idle, brain], self.projects, {}, cfg, self.now, [], [sw.Idea(id="i", text="t", created_at=0)])
        self.assertEqual([a.kind for a in acts], [])
        self.assertEqual(st["pending_items"], 2)
        brain.busy = False
        acts, st = sw.plan_tick([idle, brain], self.projects, st, cfg, self.now, [], [sw.Idea(id="i", text="t", created_at=0)])
        tour = [a for a in acts if a.kind == "tour"]
        self.assertEqual(len(tour), 1)
        self.assertEqual(sorted(i["kind"] for i in tour[0].payload["items"]), ["idea", "idle"])
        acts, _ = sw.plan_tick([idle, brain], self.projects, st, cfg, self.now + 60, [], [])
        self.assertEqual([a.kind for a in acts], [])   # tour_minutes dolmadı

    def test_phase_model_effort(self):
        cfg = _cfg(planning_effort="high", planned_model="claude-sonnet-5-5")
        self.assertEqual(sw.phase_model_effort(sw.Project(name="x", phase="planning"), cfg), ("", "high"))
        self.assertEqual(sw.phase_model_effort(sw.Project(name="x", phase="planned"), cfg), ("claude-sonnet-5-5", ""))
        self.assertEqual(sw.phase_model_effort(sw.Project(name="x", phase="planned", model="m", effort="e"), cfg), ("m", "e"))


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


class CardCoreTest(_Tmp):
    def test_build_raw_card_reads_doc_heads_and_git(self):
        repo = _make_repo(os.path.join(self.dir.name, "r"), **{"GOAL.md": "# amaç\nBir kitap yazmak\n",
                                                                "TODO.md": "- [ ] bölüm 3\n"})
        raw = sw.build_raw_card(repo)
        self.assertEqual(sorted(raw["docs"]), ["GOAL.md", "TODO.md"])
        self.assertEqual(len(raw["git_log"]), 1)
        self.assertIn("ilk commit", raw["git_log"][0])
        self.assertGreater(raw["last_commit"], 0)
        self.assertEqual(raw["source_hash"], sw.build_raw_card(repo)["source_hash"])   # kararlı
        with open(os.path.join(repo, "TODO.md"), "a") as f:
            f.write("- [ ] bölüm 4\n")
        self.assertNotEqual(sw.build_raw_card(repo)["source_hash"], raw["source_hash"])   # belge değişti
        h1 = sw.build_raw_card(repo)["source_hash"]
        _git(repo, "commit", "-q", "--allow-empty", "-m", "ikinci")
        self.assertNotEqual(sw.build_raw_card(repo)["source_hash"], h1)                    # commit değişti

    def test_raw_card_without_git_or_docs(self):
        plain = os.path.join(self.dir.name, "plain")
        os.makedirs(plain)
        raw = sw.build_raw_card(plain)
        self.assertEqual((raw["docs"], raw["git_log"], raw["last_commit"]), ({}, [], 0.0))
        self.assertEqual(sw.build_raw_card("")["docs"], {})
        # .git'i olmayan alt klasör üst deponun geçmişini ALMAZ
        repo = _make_repo(os.path.join(self.dir.name, "outer"), **{"TODO.md": "x"})
        sub = os.path.join(repo, "sub")
        os.makedirs(sub)
        self.assertEqual(sw.build_raw_card(sub)["git_log"], [])

    def test_parse_card_json_variants(self):
        ok = sw.parse_card_json(GOOD_JSON)
        self.assertEqual((ok["goal"], ok["phase_guess"], ok["next_step"], ok["open_tbds"]),
                         ("Bir kitap yaz", "planned", "3. bölümü bitir", ["TBD#1 kapak?"]))
        self.assertEqual(sw.parse_card_json("```json\n" + GOOD_JSON + "\n```")["next_step"], "3. bölümü bitir")
        self.assertEqual(sw.parse_card_json("İşte kart:\n" + GOOD_JSON + "\nUmarım yardımcı olur.")["goal"], "Bir kitap yaz")
        bad_phase = sw.parse_card_json('{"next_step": "x", "phase_guess": "bogus", "open_tbds": "tek", "blockers": 5}')
        self.assertEqual((bad_phase["phase_guess"], bad_phase["open_tbds"], bad_phase["blockers"]), ("", ["tek"], []))
        long_list = sw.parse_card_json(json.dumps({"next_step": "n", "recent_done": [f"i{n}" for n in range(30)]}))
        self.assertEqual(len(long_list["recent_done"]), sw.CARD_LIST_ITEMS)
        for junk in ("", "özet yok", "{bozuk", "[1, 2]", '{"alakasiz": 1}', "{}"):
            self.assertIsNone(sw.parse_card_json(junk), junk)

    def test_make_card_falls_back_to_raw_fields(self):
        raw = {"docs": {"GOAL.md": "# amaç\nKitap yazmak", "TOBEDECIDED.md": "- TBD#1 kapak\n- not\n"},
               "git_log": ["abc1234 2026-10-19 bölüm 2 bitti", "def5678 2026-10-18 bölüm 1"], "last_commit": 1234.0,
               "source_hash": "h"}
        proj = sw.Project(name="kitap", phase="planned")
        ham = sw.make_card(raw, None, proj, now=50.0)
        self.assertFalse(ham["summarized"])
        self.assertEqual((ham["goal"], ham["phase_guess"], ham["next_step"], ham["open_tbds"], ham["last_activity"],
                          ham["source_hash"], ham["updated_at"]),
                         ("Kitap yazmak", "planned", "", ["TBD#1 kapak"], 1234.0, "h", 50.0))
        self.assertEqual(ham["recent_done"], ["bölüm 2 bitti", "bölüm 1"])
        # model özeti dolu alanları ezer, boş olanlar ham türetimde kalır
        full = sw.make_card(raw, {"goal": "", "next_step": "bölüm 3", "open_tbds": [], "blockers": ["x"],
                                  "recent_done": [], "phase_guess": ""}, proj, now=60.0, meta={"model": "m"})
        self.assertTrue(full["summarized"])
        self.assertEqual((full["goal"], full["next_step"], full["blockers"], full["open_tbds"], full["model"]),
                         ("Kitap yazmak", "bölüm 3", ["x"], ["TBD#1 kapak"], "m"))

    def test_refresh_reason_matrix_and_failure_backoff(self):
        now = 1_000_000.0
        card = {"source_hash": "h", "updated_at": now - 3600}
        reason = lambda c, h="h", age=24: sw.card_refresh_reason(c, h, now, age)   # noqa: E731
        self.assertEqual(reason(None), "missing")
        self.assertEqual(reason(card), "")
        self.assertEqual(reason(card, "h2"), "changed")
        self.assertEqual(reason(dict(card, stale=True)), "stale")
        self.assertEqual(reason(dict(card, updated_at=now - 25 * 3600)), "old")
        self.assertEqual(reason(dict(card, updated_at=now - 25 * 3600), age=0), "")      # 0 = yaşa bakma
        # başarısız deneme: aynı kaynak için max_age dolana kadar yeniden denenmez
        failed = dict(card, stale=True, attempt_hash="h", attempt_at=now - 600)
        self.assertEqual(reason(failed), "")
        self.assertEqual(reason(dict(failed, attempt_at=now - 25 * 3600)), "stale")
        self.assertEqual(reason(failed, "h2"), "stale")                                  # kaynak değişti: backoff yok
        self.assertEqual(reason(dict(card, attempt_hash="h", attempt_at=now - 600, updated_at=now - 30 * 3600)), "")
        sw.save_card("p", {"source_hash": "old", "updated_at": 1.0, "next_step": "korunur"})
        sw.note_card_failure("p", "new", "boom", now=77.0)
        c = sw.load_card("p")
        self.assertEqual((c["next_step"], c["attempt_hash"], c["attempt_at"], c["last_error"]), ("korunur", "new", 77.0, "boom"))
        sw.note_card_failure("yok", "x", "e")                    # kart yoksa no-op
        self.assertIsNone(sw.load_card("yok"))

    def test_store_stale_and_listing(self):
        sw.save_card("a", {"next_step": "n1", "updated_at": 5.0})
        sw.save_card("b", {"next_step": "n2"})
        self.assertEqual(sorted(sw.load_cards()), ["a", "b"])
        self.assertTrue(sw.mark_card_stale("a"))
        self.assertFalse(sw.mark_card_stale("a"))
        self.assertFalse(sw.mark_card_stale("yok"))
        self.assertTrue(sw.load_card("a")["stale"])
        self.assertEqual(sw.card_one_liner(sw.load_card("b")), "n2")
        self.assertEqual(sw.card_one_liner(None), "")

    def test_model_pick_prompt_and_tour_rendering(self):
        self.assertEqual(sw.pick_card_model("elle", ["claude-haiku-4-5"], "dflt"), "elle")
        self.assertEqual(sw.pick_card_model("", ["claude-sonnet-5-5", "claude-haiku-3", "claude-haiku-4-5"], "dflt"), "claude-haiku-4-5")
        self.assertEqual(sw.pick_card_model("", ["claude-sonnet-5-5"], "dflt"), "dflt")
        prompt = sw.build_card_prompt("kitap", {"docs": {"TODO.md": "- [ ] bölüm 3"}, "git_log": ["abc 2026-10-19 x"]},
                                      sw.Project(name="kitap", goal="Kitap"), "tr")
        for needle in ("kitap", "=== TODO.md ===", "bölüm 3", "git log", "next_step", "Kayıtlı amaç: Kitap"):
            self.assertIn(needle, prompt)
        tour = sw.build_tour_prompt([{"kind": "idle", "name": "kitap", "phase": "planned",
                                      "card": {"next_step": "bölüm 3", "open_tbds": ["TBD#1"], "updated_at": time.time()},
                                      "docs": {"TODO.md": "HAM-BELGE"}}], "tr")
        self.assertIn("sıradaki adım: bölüm 3", tour)
        self.assertNotIn("HAM-BELGE", tour)           # kart varsa ham belge başı gitmez
        self.assertIn("HAM-BELGE", sw.build_tour_prompt([{"kind": "idle", "name": "k", "docs": {"TODO.md": "HAM-BELGE"}}], "tr"))


class OneshotProviderTest(unittest.TestCase):
    def test_claude_argv_shape_and_unsupported_default(self):
        from claudeops.providers import claude_provider as cp
        with mock.patch.object(cp, "claude_help_text", lambda binary=None: "  --tools <tools...>  --no-session"):
            argv = get_provider("claude").oneshot_argv("özetle", "claude-haiku-4-5")
            self.assertNotIn("--model", get_provider("claude").oneshot_argv("x", ""))
        self.assertEqual(argv[1:3], ["-p", "özetle"])      # prompt -p'den hemen sonra, variadic --tools'tan ÖNCE
        self.assertEqual(argv[-4:], ["--output-format", "text", "--tools", ""])
        self.assertEqual(argv[argv.index("--model") + 1], "claude-haiku-4-5")
        self.assertNotIn("--no-session-persistence", argv)   # `--no-session` tam eşleşme DEĞİL → bayrak yok
        # ikili bayrağı tanıyorsa transkript bırakmasın; `--tools ""` (variadic) yine EN SONDA
        with mock.patch.object(cp, "claude_help_text", lambda binary=None: "--no-session-persistence  Disable session persistence"):
            argv = get_provider("claude").oneshot_argv("özetle", "m")
        self.assertEqual(argv[-5:], ["text", "--no-session-persistence", "--tools", ""][-4:] and
                         ["--output-format", "text", "--no-session-persistence", "--tools", ""])
        # çalıştırılamayan ikili: "" (ve önbelleğe alınmaz) → bayrak eklenmez
        cp._HELP_CACHE.clear()
        self.assertEqual(cp.claude_help_text("/yok/boyle/claude"), "")
        self.assertFalse(cp.claude_supports_flag("--no-session-persistence", "/yok/boyle/claude"))
        self.assertEqual(cp._HELP_CACHE, {})
        # gerçek bir ikili (python) ile: --help çıktısı (yol, mtime, boyut) anahtarıyla bir kez okunur
        self.assertIn("usage", cp.claude_help_text(sys.executable).lower())
        self.assertEqual(len(cp._HELP_CACHE), 1)
        for cli in ("agy", "codex", "copilot", "ucli"):
            self.assertIsNone(get_provider(cli).oneshot_argv("x", None), cli)
        self.assertIsNone(get_provider("agy").oneshot("x", None, "/tmp"))

    def test_ucli_oneshot_uses_chat_once_without_key_in_argv(self):
        from claudeops.providers import ucli_provider
        prov = get_provider("ucli")
        seen = {}

        def fake_once(root, prompt, **kw):
            seen.update(root=root, prompt=prompt, **kw)
            return {"answer": "  {\"goal\": \"x\"}  "}

        with mock.patch.object(ucli_provider, "ucli_chat_once", fake_once), \
                mock.patch.object(ucli_provider, "byok_env_for", lambda cli: {"UCLI_API_KEY": "sk-gizli"}):
            self.assertEqual(prov.oneshot("özetle", "m1", os.path.join(tempfile.gettempdir(), "cops-oneshot-test")), '{"goal": "x"}')
        self.assertEqual((seen["model"], seen["endpoint"], seen["api_key"]), ("m1", ucli_provider._ENDPOINT, "sk-gizli"))
        with mock.patch.object(ucli_provider, "ucli_chat_once", lambda *a, **k: {"answer": ""}), \
                mock.patch.object(ucli_provider, "byok_env_for", lambda cli: {}):
            with self.assertRaises(OneshotError):
                prov.oneshot("x", None, tempfile.gettempdir())

    def test_oneshot_runs_argv_and_reports_failures(self):
        prov = get_provider("claude")   # taban `oneshot` somut sağlayıcıda; argv'yi biz veriyoruz
        tmp = tempfile.gettempdir()

        def run(argv, **kw):
            with mock.patch.object(prov, "oneshot_argv", return_value=argv):
                return prov.oneshot("p", None, tmp, **kw)

        self.assertEqual(run([sys.executable, "-c", "import sys; print(sys.stdin.read() == '', 'cwd-ok')"]), "True cwd-ok")
        fresh = os.path.join(tempfile.mkdtemp(), "henüz", "yok")           # nötr cwd ilk çağrıda kendiliğinden açılır
        with mock.patch.object(prov, "oneshot_argv", return_value=[sys.executable, "-c", "print('x')"]):
            self.assertEqual(prov.oneshot("p", None, fresh), "x")
        self.assertTrue(os.path.isdir(fresh))
        for argv, kw in (([sys.executable, "-c", "import sys; sys.exit(3)"], {}),
                         ([sys.executable, "-c", "pass"], {}),                            # boş yanıt
                         ([sys.executable, "-c", "import time; time.sleep(5)"], {"timeout": 0.5}),
                         (["/yok/boyle/bir/ikili"], {})):
            with self.assertRaises(OneshotError, msg=str(argv)):
                run(argv, **kw)


class SimilarAnswersTest(unittest.TestCase):
    def _q(self, i, proj, text, ans, at=100.0):
        return sw.Question(id=i, project=proj, text=text, created_at=1.0, status="answered", answer=ans, answered_at=at)

    def test_ranks_by_similarity_and_excludes_self(self):
        qs = [self._q("a", "zlkrn", "G8 sentezi için Opus high oturumu açılsın mı?", "evet"),
              self._q("b", "mkt", "Kaynakça biçimi APA mı olsun?", "APA"),
              self._q("c", "zlkrn", "G8 yazımı Fable high ile mi yapılsın?", "hayır sonnet", at=200.0)]
        got = sw.similar_answers("G8 için Opus high oturumu ne zaman açılsın?", qs, project="zlkrn")
        self.assertEqual([q.id for q in got][:1], ["a"])
        self.assertNotIn("b", [q.id for q in got])
        self.assertEqual(sw.similar_answers("G8 için Opus high oturumu ne zaman açılsın?", qs, exclude_id="a")[0].id, "c")

    def test_open_or_unanswered_ignored_and_prompt_renders(self):
        qs = [sw.Question(id="o", project="p", text="G8 Opus high mı?", created_at=1.0)]
        self.assertEqual(sw.similar_answers("G8 Opus high mı?", qs), [])
        it = {"kind": "routine", "name": "p", "id": "r1", "text": "soru?",
              "similar": [{"project": "p", "text": "eski soru", "answer": "eski cevap"}]}
        self.assertIn("benzer geçmiş karar [p]: eski soru → eski cevap", sw.build_tour_prompt([it]))


class RosterGateTest(_Tmp):
    def test_active_phase_needs_roster_but_idea_does_not(self):
        with mock.patch.object(web_steward, "_in_roster", lambda name: False):
            r = web_steward.http_project_upsert({"name": "zzz", "phase": "planned"})
            self.assertFalse(r["ok"])
            self.assertIn("roster", r["error"])
            self.assertTrue(web_steward.http_project_upsert({"name": "zzz", "phase": "idea"})["ok"])
            # fazı değiştirmeyen güncelleme (not) roster'a bakmaz; idea→planned dahil aktif faza geçiş bakar
            self.assertTrue(web_steward.http_project_upsert({"name": "zzz", "notes": "x"})["ok"])
            self.assertFalse(web_steward.http_project_upsert({"name": "zzz", "phase": "planned"})["ok"])


class ShutdownPlanTest(unittest.TestCase):
    def _run(self, views, sd, now):
        projects = {"p1": sw.Project(name="p1", phase="planned"), "p2": sw.Project(name="p2", phase="planned")}
        return sw.plan_shutdown(views, projects, sd, _cfg(), now)

    def test_waits_for_quiet_then_handover_then_stop_then_brain(self):
        t = 10000.0
        brain = _view("degnekci", last_activity=t - 500)
        busy = _view("p1", busy=True, last_activity=t - 5)
        quiet = _view("p2", busy=False, last_activity=t - 300)
        acts, sd, done = self._run([busy, quiet, brain], {}, t)
        self.assertEqual([(a.kind, a.name) for a in acts], [("handover", "p2")])
        self.assertFalse(done)
        self.assertEqual(sd["items"]["p1"]["stage"], "wait")
        # p2 asistanı READY dedi; p1 hâlâ meşgul: yalnız p2 durdurulur, beyin henüz beklemede
        ready = _view("p2", busy=False, last_activity=t + 10, last_assistant="READY FOR HANDOVER")
        acts, sd, done = self._run([busy, ready, brain], sd, t + 60)
        self.assertEqual([(a.kind, a.name) for a in acts], [("stop", "p2")])
        self.assertNotIn("degnekci", sd["items"])
        # p1 sessizleşir -> devir; sonra RFH -> durdur; sonra beyin
        q1 = _view("p1", busy=False, last_activity=t - 200)
        acts, sd, _ = self._run([q1, brain], sd, t + 120)
        self.assertEqual([(a.kind, a.name) for a in acts], [("handover", "p1")])
        r1 = _view("p1", busy=False, last_activity=t + 200, last_assistant="READY FOR HANDOVER")
        acts, sd, done = self._run([r1, brain], sd, t + 180)
        self.assertEqual([(a.kind, a.name) for a in acts], [("stop", "p1"), ("handover", "degnekci")])   # projeler bitti: beyin sırası aynı adımda
        self.assertFalse(done)
        rb = _view("degnekci", busy=False, last_activity=t + 400, last_assistant="READY FOR HANDOVER")
        acts, sd, done = self._run([rb], sd, t + 300)
        self.assertEqual([(a.kind, a.name) for a in acts], [("stop", "degnekci")])
        acts, sd, done = self._run([], sd, t + 360)
        self.assertTrue(done)

    def test_subagent_blocks_and_timeouts_leave_session_open(self):
        t = 10000.0
        v = _view("p1", busy=False, last_activity=t - 300, subagent_active=True)
        acts, sd, done = self._run([v], {}, t)
        self.assertEqual(acts, [])
        acts, sd, done = self._run([v], sd, t + sw.SHUTDOWN_WAIT_MAX_SECONDS + 1)
        self.assertEqual((acts, sd["items"]["p1"]["stage"], done), ([], "busy_left", True))
        # devir gönderildi ama cevap yok -> ho_timeout, durdurulmaz
        q = _view("p1", busy=False, last_activity=t - 300)
        _, sd, _ = self._run([q], {}, t)
        acts, sd, done = self._run([q], sd, t + sw.SHUTDOWN_HO_MAX_SECONDS + 1)
        self.assertEqual((acts, sd["items"]["p1"]["stage"], done), ([], "ho_timeout", True))

    def test_stale_ready_text_before_handover_does_not_count(self):
        t = 10000.0
        q = _view("p1", busy=False, last_activity=t - 300, last_assistant="READY FOR HANDOVER")
        _, sd, _ = self._run([q], {}, t)                     # devir gönderildi (stage ho, at=t)
        acts, sd, _ = self._run([q], sd, t + 30)             # etkinlik t'den ESKİ: eski RFH metni sayılmaz
        self.assertEqual(acts, [])


class OpenQuestionMergeTest(_Tmp):
    """Aynı projeden AÇIK (cevapsız) benzer soru yeniden açılmaz: birleştirilir, sayaç artar (cli aynı soruyu 3 kez açtı)."""

    def test_paraphrased_open_question_is_merged(self):
        q1 = sw.add_question("cli", "ncs koşu kayıtlarının yolu nerede? reviews/ncs/evren altında mı yoksa reviewer dizininde mi?", source="cli")
        q2 = sw.add_question("cli", "ncs koşu kayıtlarının yolu: reviews/ncs/evren altında mı yoksa reviewer dizininde mi bulunur?", source="cli")
        q3 = sw.add_question("cli", "ncs koşu kayıtlarının yolu nedir, reviews/ncs/evren altında mı yoksa reviewer dizininde mi?", source="cli")
        self.assertEqual(q1.id, q2.id)
        self.assertEqual(q1.id, q3.id)
        self.assertEqual(len(sw.open_questions()), 1)
        self.assertEqual(sw.find_question(q1.id).asked_again, 2)
        self.assertEqual(sw.find_question(q1.id).notified_at, 0.0)        # birleştirme yeniden bildirim doğurmaz (zaten bildirilmişse korunur)

    def test_other_project_or_topic_not_merged(self):
        a = sw.add_question("cli", "ncs koşu kayıtlarının yolu reviews/ncs/evren altında mı?")
        b = sw.add_question("vc", "ncs koşu kayıtlarının yolu reviews/ncs/evren altında mı?")          # başka proje
        c = sw.add_question("cli", "Evren günlük kotası bitince reviewer hangi modele geçsin?")        # başka konu
        self.assertEqual(len({a.id, b.id, c.id}), 3)

    def test_short_distinct_questions_not_merged(self):
        a = sw.add_question("p", "x soru 3?")
        b = sw.add_question("p", "x soru 4?")
        self.assertNotEqual(a.id, b.id)

    def test_routine_question_promoted_when_asked_to_owner(self):
        r, how = sw.add_question_ex("cli", "ncs koşu kayıtlarının yolu reviews/ncs/evren altında mı?", routine=True)
        self.assertEqual(how, "new")
        self.assertTrue(r.routine)
        q, how = sw.add_question_ex("cli", "ncs koşu kayıtlarının yolu reviews/ncs/evren altında mı?")      # aynı metin, sahibe
        self.assertEqual((q.id, how, q.routine), (r.id, "promoted", False))
        q2, how2 = sw.add_question_ex("cli", "ncs koşu kayıtlarının yolu reviews/ncs/evren altında mı?")
        self.assertEqual((q2.id, how2), (r.id, "same"))                                                        # bir daha yükseltme yok
        a, _ = sw.add_question_ex("cli", "zlkrn dosya yolu hangi dizinde tutulmalı sizce kesin olarak?", routine=True)
        b, how3 = sw.add_question_ex("cli", "zlkrn dosya yolu hangi dizinde tutulmalı sizce kesin olarak mı?")  # benzer, sahibe
        self.assertEqual((b.id, how3, b.routine), (a.id, "promoted", False))
        c, how4 = sw.add_question_ex("cli", "zlkrn dosya yolu hangi dizinde tutulmalı sizce kesin olarak peki?", routine=True)
        self.assertEqual((c.id, how4), (a.id, "merged"))                                                        # rutin sahibe soruyu geri çevirmez
        self.assertFalse(sw.find_question(a.id).routine)

    def test_answered_question_not_merged_into_open_path(self):
        q1 = sw.add_question("cli", "ncs koşu kayıtlarının yolu reviews/ncs/evren altında mı?")
        sw.answer_question(q1.id, "evet")
        q2 = sw.add_question("cli", "ncs koşu kayıtlarının yolu reviews/ncs/evren altında mı?")
        self.assertEqual(q1.id, q2.id)                                                                  # cevaplı yol (REASK) eskisi gibi
        self.assertEqual(sw.find_question(q1.id).repeats, 1)
        self.assertEqual(sw.find_question(q1.id).asked_again, 0)


class SalientReaskTest(unittest.TestCase):
    def _a(self, text, ans="evet"):
        return sw.Question(id="q1", project="p1", text=text, created_at=1.0, status="answered", answer=ans, answered_at=100.0)

    def test_paraphrased_same_topic_is_duplicate(self):
        old = self._a("Kalan işler G8 sentezi (Opus high), G8 yazımı. Sonra yazım için Fable high mı?")
        new = "Bu oturumda yapılabilir iş kalmadı. Yeniden açılış sırası G8 için Opus high, ardından yazım için Fable high mı"
        self.assertIsNotNone(sw.find_answered_duplicate([old], "p1", new, now=200.0))

    def test_different_topic_not_duplicate(self):
        old = self._a("Kalan işler G8 sentezi (Opus high), yazım Fable high mı?")
        self.assertIsNone(sw.find_answered_duplicate([old], "p1", "G6 ve G7 için kaynak arama sırası Sonnet medium ile mi?", now=200.0))


class DoneDeferralTest(unittest.TestCase):
    def test_done_deferred_while_subagent_then_applied(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        v = _view("p1", last_assistant="iş bitti\nSTEWARD-DONE", subagent_active=True)
        acts, st = sw.plan_tick([v], projects, {}, _cfg(), 5000.0, [], [])
        self.assertEqual([a for a in acts if a.kind in ("set_phase", "stop")], [])
        self.assertEqual(st["done_pending"], {"p1": "p1"})
        v2 = _view("p1", last_assistant="iş bitti\nSTEWARD-DONE", subagent_active=False)
        acts, st = sw.plan_tick([v2], projects, st, _cfg(), 5200.0, [], [])
        self.assertEqual([(a.kind, a.name) for a in acts if a.kind in ("set_phase", "stop")], [("set_phase", "p1"), ("stop", "p1")])
        self.assertNotIn("done_pending", st)

    def test_deferred_done_dropped_when_no_done_tag_added_later(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        acts, st = sw.plan_tick([_view("p1", last_assistant="iş bitti\nSTEWARD-DONE", subagent_active=True)],
                                projects, {}, _cfg(), 5000.0, [], [])
        self.assertEqual(st["done_pending"], {"p1": "p1"})
        projects["p1"].notes = "sürekli geliştirme " + sw.NO_DONE_TAG
        acts, st = sw.plan_tick([_view("p1", last_assistant="iş bitti\nSTEWARD-DONE", subagent_active=False)],
                                projects, st, _cfg(), 5200.0, [], [])
        self.assertEqual([a for a in acts if a.kind in ("set_phase", "stop")], [])
        self.assertNotIn("done_pending", st)

    def test_done_immediate_without_subagent(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        acts, _ = sw.plan_tick([_view("p1", last_assistant="STEWARD-DONE")], projects, {}, _cfg(), 5000.0, [], [])
        self.assertEqual([a.kind for a in acts if a.kind in ("set_phase", "stop")], ["set_phase", "stop"])


class IdleSkipTest(unittest.TestCase):
    def test_no_idle_item_for_waiting_or_done_projects(self):
        now = 100000.0
        projects = {"p1": sw.Project(name="p1", phase="planned"), "p2": sw.Project(name="p2", phase="done")}
        views = [_view("p1", last_activity=1.0, started_at=1.0), _view("p2", last_activity=1.0, started_at=1.0)]
        items = sw.review_items(views, projects, _cfg(), now, [], [])
        self.assertEqual([i["name"] for i in items if i["kind"] == "idle"], ["p1"])    # p2 done: boşta sayılmaz
        q = sw.Question(id="q1", project="p1", text="?", created_at=1.0, source="p1")
        items = sw.review_items(views, projects, _cfg(), now, [q], [])
        self.assertEqual([i for i in items if i["kind"] == "idle"], [])               # p1 sahibini bekliyor


class MergedAnswersTest(unittest.TestCase):
    def _q(self, i, ans):
        return sw.Question(id=i, project="p1", text=f"soru {i}?", created_at=1.0, status="answered", answer=ans,
                           answered_at=2.0, source="p1")

    def test_planner_merges_same_session_answers_in_one_action(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        qs = [self._q("a", "evet"), self._q("b", "hayır"), self._q("c", "sıradan")]
        acts, _ = sw.plan_tick([_view("p1", last_assistant="")], projects, {}, _cfg(), 5000.0, qs, [])
        dl = [a for a in acts if a.kind == "deliver_answer"]
        self.assertEqual(len(dl), 1)
        self.assertEqual([dl[0].payload["question_id"]] + dl[0].payload["more_ids"], ["a", "b", "c"])

    def test_answer_waits_while_subagent_active(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        qs = [self._q("a", "evet")]
        acts, _ = sw.plan_tick([_view("p1", last_assistant="", subagent_active=True)], projects, {}, _cfg(), 5000.0, qs, [])
        self.assertEqual([a for a in acts if a.kind == "deliver_answer"], [])
        acts, _ = sw.plan_tick([_view("p1", last_assistant="")], projects, {}, _cfg(), 5000.0, qs, [])
        self.assertEqual(len([a for a in acts if a.kind == "deliver_answer"]), 1)

    def test_subagent_active_for_reads_mtime(self):
        import tempfile
        import unittest.mock as um
        from claudeops.commands import web_steward as ws
        with tempfile.TemporaryDirectory() as d:
            tr = os.path.join(d, "abc.jsonl")
            open(tr, "w").close()
            sub = os.path.join(d, "abc", "subagents")
            os.makedirs(sub)
            f = os.path.join(sub, "agent-x.jsonl")
            open(f, "w").close()
            with um.patch("claudeops.providers.claude_provider.jsonl_path_for", return_value=tr):
                self.assertTrue(ws.subagent_active_for("/x", "abc"))
                old = os.path.getmtime(f) - 1000
                os.utime(f, (old, old))
                self.assertFalse(ws.subagent_active_for("/x", "abc"))

    def test_compact_answer_directive_drops_preamble(self):
        p = sw.Project(name="p1", phase="planned", goal="AMAÇ-X", notes="NOT-Y")
        full = sw.build_directive(p, extra="Cevaba göre devam et.", answer=self._q("a", "evet"))
        small = sw.build_directive(p, extra="Cevaba göre devam et.", answer=self._q("a", "evet"), compact=True)
        for needle in ("AMAÇ-X", "NOT-Y", "Değnekçi protokolü"):
            self.assertIn(needle, full)
            self.assertNotIn(needle, small)
        self.assertIn("Cevabım: evet", small)
        self.assertLess(len(small), len(full) // 2)
        # cevapsız faz direktifi compact'tan etkilenmez
        self.assertIn("Değnekçi protokolü", sw.build_directive(p, compact=True))

    def test_directive_contains_all_answers(self):
        p = sw.Project(name="p1", phase="planned")
        msg = sw.build_directive(p, answer=self._q("a", "evet"), more=[self._q("b", "hayır")])
        self.assertIn("Cevabım: evet", msg)
        self.assertIn("soru b?", msg)
        self.assertIn("Cevabım: hayır", msg)


class ScanTicksTest(unittest.TestCase):
    def test_leading_code_tick_in_question_kept(self):
        m = sw.scan_markers("STEWARD-ASK: `dano_2023_federated` (Light Reading) alınsın mı?")
        self.assertEqual(m["asks"], ["`dano_2023_federated` (Light Reading) alınsın mı?"])

    def test_wrapped_marker_and_wrapped_body(self):
        self.assertEqual(sw.scan_markers("`STEWARD-ASK: Devam mı?`")["asks"], ["Devam mı?"])
        self.assertEqual(sw.scan_markers("STEWARD-IDEA: `tek parça fikir`")["ideas"], ["tek parça fikir"])


class PlanMarkersTest(unittest.TestCase):
    """Değnekçi kapalıyken salt kayıt taraması: yalnız soru/fikir, oturuma/faza dokunmaz."""

    def _projects(self):
        return {"p1": sw.Project(name="p1", phase="planned")}

    def test_records_asks_and_ideas_only(self):
        v = _view("p1", last_assistant="STEWARD-ASK: Hangi yol?\nSTEWARD-IDEA: yeni\nSTEWARD-DONE\nSTEWARD-PLAN-READY")
        acts, st = sw.plan_markers([v], self._projects(), {}, _cfg())
        self.assertEqual([(a.kind, a.reason) for a in acts], [("ask_user", "STEWARD-ASK"), ("idea", "STEWARD-IDEA")])
        self.assertIn("p1", st["seen_assistant"])

    def test_same_reply_not_rescanned_and_routine_needs_question_mark(self):
        v = _view("p1", last_assistant="STEWARD-ROUTINE: bekliyorum\nSTEWARD-ROUTINE: Devam mı?")
        acts, st = sw.plan_markers([v], self._projects(), {}, _cfg())
        self.assertEqual([a.payload["text"] for a in acts], ["Devam mı?"])
        again, _ = sw.plan_markers([v], self._projects(), st, _cfg())
        self.assertEqual(again, [])

    def test_matches_plan_tick_marker_actions(self):
        v = _view("p1", last_assistant="STEWARD-ASK: a?\nSTEWARD-BLOCKED: x\nSTEWARD-IDEA: i")
        passive, _ = sw.plan_markers([v], self._projects(), {}, _cfg())
        full, _ = sw.plan_tick([v], self._projects(), {}, _cfg(), 5000.0, [], [])
        keep = [(a.kind, a.reason, a.payload) for a in full if a.kind in ("ask_user", "idea")]
        self.assertEqual([(a.kind, a.reason, a.payload) for a in passive], keep)


class ObserveCoreTest(unittest.TestCase):
    def test_filter_act_passes_everything_and_clears_traces(self):
        acts = [sw.Action("start", "a"), sw.Action("handover", "b")]
        st = {"observed": {"x": 1.0}, "observed_visit": {"a": 1.0}, "keep": 1}
        apply, dry, new = sw.observe_filter(acts, "act", st, 100.0)
        self.assertEqual((apply, dry), (acts, []))
        self.assertEqual(new, {"keep": 1})

    def test_filter_observe_splits_dedups_and_prunes(self):
        acts = [sw.Action("handover", "a"), sw.Action("start", "b", "due"), sw.Action("ask_user", "c"),
                sw.Action("idea", "c"), sw.Action("set_phase", "c"), sw.Action("deliver_answer", "d", payload={"question_id": "q1"}),
                sw.Action("tour", "degnekci"), sw.Action("stop", "e"), sw.Action("respawn", "f")]
        apply, dry, st = sw.observe_filter(acts, "observe", {}, 1000.0)
        self.assertEqual([a.kind for a in apply], ["ask_user", "idea", "set_phase"])    # oturuma dokunmayanlar çalışır
        self.assertEqual([a.kind for a in dry], ["handover", "start", "deliver_answer", "tour", "stop", "respawn"])
        self.assertEqual(st["observed_visit"], {"b": 1000.0})                              # yalnız soru dışı start
        # aynı anahtarlar pencere içinde tekrar raporlanmaz; farklı soru id'si yeni anahtardır
        again = [sw.Action("handover", "a"), sw.Action("deliver_answer", "d", payload={"question_id": "q1"}),
                 sw.Action("deliver_answer", "d", payload={"question_id": "q2"}), sw.Action("start", "g")]
        _, dry2, st2 = sw.observe_filter(again, "observe", st, 1000.0 + 60)
        self.assertEqual([(a.kind, a.name) for a in dry2], [("deliver_answer", "d"), ("start", "g")])
        # pencere dolunca tekrar raporlanır
        _, dry3, _ = sw.observe_filter([sw.Action("handover", "a")], "observe", st2, 1000.0 + sw.OBSERVE_DEDUP_SECONDS + 1)
        self.assertEqual(len(dry3), 1)

    def test_observed_visit_paces_due_projects_across_ticks(self):
        now = 1_000_000.0
        projects = {"a": sw.Project(name="a", phase="planned", priority=1, cadence_minutes=240),
                    "b": sw.Project(name="b", phase="planned", priority=2, cadence_minutes=240)}
        cfg = _cfg(max_starts_per_tick=1)
        state = {}
        started = []
        for n in range(4):
            acts, state = sw.plan_tick([], projects, state, cfg, now + n * 120, [], [])
            apply, dry, state = sw.observe_filter(acts, "observe", state, now + n * 120)
            started += [a.name for a in dry]
        self.assertEqual(started, ["a", "b"])        # her proje cadence içinde BİR kez "would:start"; sonsuz tekrar yok
        acts, state = sw.plan_tick([], projects, state, cfg, now + 241 * 60, [], [])
        self.assertEqual([a.name for a in acts], ["a"])   # cadence dolunca yine sıra gelir


class SummaryCoreTest(_Tmp):
    @staticmethod
    def _e(event, ts="2026-10-19T10:00:00", **kw):
        return {"ts": ts, "event": event, **kw}

    def test_daily_summary_counts_and_filters_by_date(self):
        e = self._e
        entries = [
            e("tick", mode="observe", trigger="timer", n=0, dry=2, error=""),
            e("tick", mode="observe", trigger="manual", n=1, dry=0, error=""),
            e("tick", mode="observe", trigger="timer", n=0, dry=0, error="boom"),
            e("action", kind="handover", name="a", ok=True), e("action", kind="stop", name="b", ok=False),
            e("action", kind="ask_user", name="a", ok=True), e("ask", id="q9", project="x"),
            e("answer", id="q9"), e("action", kind="idea", name="a", ok=True),
            e("action", kind="set_phase", name="kitap", ok=True, reason="STEWARD-PLAN-READY"),
            e("would:start", name="p1"), e("would:start", name="p2"), e("would:handover", name="a"),
            e("card", name="c1", ok=True), e("card", name="c2", ok=False), e("directive", name="a"),
            e("tick", ts="2026-10-18T10:00:00", mode="act", trigger="timer"),       # başka gün
            e("would:start", ts="2026-10-18T10:00:00", name="eski"),
        ]
        text = sw.daily_summary(entries, "2026-10-19", "tr", {"open_questions": 2, "ideas_new": 1, "pending_items": 3,
                                                              "undelivered_answers": 0})
        for needle in ("Değnekçi günlük özet — 2026-10-19", "**observe**", "Tick: 3 (1 elle, 1 hatalı)",
                       "Uygulanan eylemler: 2 — handover 1, stop 1 (1 başarısız)",
                       "Yapılacaktı (observe, uygulanmadı): 3 — handover 1 (a); start 2 (p1, p2)",
                       "Sorular: 2 açıldı, 1 cevaplandı", "Fikirler: 1 yeni", "Kartlar: 1 yenilendi (c1), 1 başarısız",
                       "Handover: 1 (a)", "Direktifler: 1 (a)", "Faz değişimi: kitap (STEWARD-PLAN-READY)",
                       "Bekleyen: 2 açık soru, 1 yeni fikir, 3 gözden geçirme maddesi, 0 iletilmemiş cevap"):
            self.assertIn(needle, text)
        self.assertNotIn("eski", text)
        en = sw.daily_summary(entries, "2026-10-19", "en")
        self.assertIn("Steward daily summary", en)
        self.assertIn("Would have done (observe, not applied): 3", en)
        self.assertNotIn("Pending", en)                                             # pending verilmediyse satır yok
        empty = sw.daily_summary([], "2026-10-19", "tr")
        self.assertIn("Tick: kayıt yok", empty)
        self.assertNotIn("Mod:", empty)

    def test_summary_due(self):
        at = lambda h: time.mktime((2026, 10, 19, h, 30, 0, 0, 0, -1))   # noqa: E731
        self.assertEqual(sw.summary_due({}, at(20), 21), "")
        self.assertEqual(sw.summary_due({}, at(21), 21), "2026-10-19")
        self.assertEqual(sw.summary_due({"summary_date": "2026-10-18"}, at(23), 21), "2026-10-19")
        self.assertEqual(sw.summary_due({"summary_date": "2026-10-19"}, at(23), 21), "")
        self.assertEqual(sw.summary_due({}, at(0), 0), "2026-10-19")

    def test_log_reader_and_summary_text(self):
        sw.log_event("tick", mode="act", trigger="timer", n=1, dry=0, error="")
        sw.log_event("action", kind="handover", name="a", ok=True)
        today = time.strftime("%Y-%m-%d")
        self.assertEqual(len(sw.log_entries_for_date(today)), 2)
        self.assertEqual(sw.log_entries_for_date("1999-01-01"), [])
        sw.add_question("p", "soru?")
        sw.add_idea("fikir")
        text = sw.summary_text(today, "tr")
        self.assertIn("Tick: 1", text)
        self.assertIn("Bekleyen: 1 açık soru, 1 yeni fikir", text)
        path = sw.write_daily(today, text)
        self.assertTrue(path.endswith(os.path.join("daily", today + ".md")))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), text)

    def test_compact_log_folds_ticks_and_keeps_summary_identical(self):
        def raw(ts, event, **d):
            with open(sw.LOG_JSONL, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": ts, "event": event, **d}, ensure_ascii=False) + "\n")
        os.makedirs(sw.STEWARD_DIR, exist_ok=True)
        raw("2026-10-18T23:58:00", "tick", trigger="timer", mode="observe", n=0, dry=0, error="")
        raw("2026-10-19T00:02:00", "tick", trigger="timer", mode="observe", n=0, dry=1, error="")
        raw("2026-10-19T00:04:00", "would:start", name="p1")
        raw("2026-10-19T09:00:00", "tick", trigger="manual", mode="act", n=1, dry=0, error="")
        raw("2026-10-19T09:00:01", "action", kind="start", name="p1", ok=True)
        raw("2026-10-19T12:00:00", "tick", trigger="timer", mode="act", n=0, dry=0, error="boom")
        with open(sw.LOG_JSONL, "a", encoding="utf-8") as f:
            f.write("bozuk satır\n")
        raw("2026-10-20T00:02:00", "tick", trigger="timer", mode="act", n=0, dry=0, error="")
        before = sw.daily_summary(sw.log_entries_for_date("2026-10-19"), "2026-10-19", "tr")
        self.assertIn("Tick: 3 (1 elle, 1 hatalı)", before)
        self.assertIn("Mod: **act**", before)
        self.assertEqual(sw.compact_log("2026-10-19"), 3)
        with open(sw.LOG_JSONL, encoding="utf-8") as f:
            lines = f.read().splitlines()
        events = [(json.loads(ln)["ts"], json.loads(ln)["event"]) if ln.startswith("{") else ("", ln) for ln in lines]
        self.assertEqual([e for _, e in events], ["tick", "would:start", "action", "bozuk satır", "ticks", "tick"])
        folded = json.loads(lines[4])
        self.assertEqual((folded["n"], folded["manual"], folded["errors"], folded["mode"], folded["ts"]),
                         (3, 1, 1, "act", "2026-10-19T23:59:59"))
        after = sw.daily_summary(sw.log_entries_for_date("2026-10-19"), "2026-10-19", "tr")
        self.assertEqual(before, after)                         # özet sıkıştırmadan sonra AYNI
        self.assertEqual(sw.compact_log("2026-10-19"), 0)       # ikinci kez: katlanacak tick yok, dosya değişmez
        self.assertEqual(sw.compact_log("2026-10-20"), 1)       # günün sonu dosya sonu: toplam en sona
        with open(sw.LOG_JSONL, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read().splitlines()[-1])["event"], "ticks")
        self.assertEqual(sw.compact_log("1999-01-01"), 0)
        # rotasyon: eşik altı dokunmaz, üstü .1'e devirir
        self.assertFalse(sw.rotate_log(10 ** 9))
        self.assertTrue(sw.rotate_log(10))
        self.assertFalse(os.path.exists(sw.LOG_JSONL))
        self.assertTrue(os.path.isfile(sw.LOG_JSONL + ".1"))
        self.assertFalse(sw.rotate_log(10))                     # dosya yok: sessizce False
        sw.log_event("tick", mode="observe", trigger="timer")   # sonraki ekleme yeni dosya açar
        self.assertEqual(len(sw.tail_log(5)), 1)

    def test_missed_summary_dates_and_catch_up(self):
        settings.save_settings({"steward": {"enabled": "on", "summary_hour": "21", "card_refresh": "off"}})
        cfg = settings.steward_config()
        now = time.mktime((2026, 10, 19, 9, 5, 0, 0, 0, -1))
        self.assertEqual(sw.missed_summary_dates(now), [])                     # kayıt yok: boş özet gitmez
        os.makedirs(sw.STEWARD_DIR, exist_ok=True)
        with open(sw.LOG_JSONL, "a", encoding="utf-8") as f:
            for ts, ev in (("2026-10-15T10:00:00", "tick"), ("2026-10-17T10:00:00", "tick"),
                           ("2026-10-18T10:00:00", "tick"), ("2026-10-18T10:02:00", "would:start")):
                f.write(json.dumps({"ts": ts, "event": ev, "mode": "observe", "trigger": "timer", "name": "p"}) + "\n")
        self.assertEqual(sw.missed_summary_dates(now), ["2026-10-17", "2026-10-18"])   # 15'i pencere dışı (3 gün)
        sw.write_daily("2026-10-17", "x")
        self.assertEqual(sw.missed_summary_dates(now), ["2026-10-18"])
        notes = []
        with mock.patch.object(web_steward, "notify_phone", lambda text: notes.append(text) or True):
            path = web_steward.maybe_daily_summary(cfg, now)                   # saat 9: bugün değil, dün yazılır
        self.assertTrue(path.endswith(os.path.join("daily", "2026-10-18.md")))
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].startswith("(gecikmiş özet) # Değnekçi günlük özet — 2026-10-18"))
        self.assertIn("Tick: 1", notes[0])
        self.assertNotIn("summary_date", sw.load_state())                      # bugünün işareti dokunulmadı
        self.assertEqual(sw.missed_summary_dates(now), [])
        events = [e for e in sw.tail_log(50)]
        self.assertTrue(any(e["event"] == "summary" and e.get("late") and e["date"] == "2026-10-18" for e in events))
        self.assertTrue(any(e["event"] == "log_compact" and e["ticks"] == 1 for e in events))
        self.assertEqual([e["event"] for e in sw.log_entries_for_date("2026-10-18") if e["event"] in ("tick", "ticks")], ["ticks"])
        with mock.patch.object(web_steward, "notify_phone", lambda text: notes.append(text) or True):
            self.assertIsNone(web_steward.maybe_daily_summary(cfg, now))      # tekrar: dün yazıldı, saat gelmedi
            today_path = web_steward.maybe_daily_summary(cfg, now + 12 * 3600)
        self.assertTrue(today_path.endswith("2026-10-19.md"))
        self.assertEqual(sw.load_state()["summary_date"], "2026-10-19")
        self.assertFalse(notes[-1].startswith("(gecikmiş"))


class RoutineQuestionTest(_Tmp):
    def test_marker_scan_and_session_reply_opens_routine_ask(self):
        m = sw.scan_markers("tamam\nSTEWARD-ROUTINE: Opus high oturumunu ne zaman açıyorsunuz?\nSTEWARD-ASK: Beck PDF alınsın mı?")
        self.assertEqual(m["routines"], ["Opus high oturumunu ne zaman açıyorsunuz?"])
        self.assertEqual(m["asks"], ["Beck PDF alınsın mı?"])
        cfg = _cfg(max_active=4)
        projects = {"a": sw.Project(name="a", phase="planned", cadence_minutes=60)}
        v = _view("a", last_assistant="STEWARD-ROUTINE: Şimdi mi açalım?")
        acts, _ = sw.plan_tick([v], projects, {}, cfg, 5000.0, [], [])
        got = [a for a in acts if a.reason == "STEWARD-ROUTINE"]
        self.assertEqual([(a.kind, a.payload["project"], a.payload["routine"]) for a in got], [("ask_user", "a", True)])

    def test_routine_goes_to_brain_tour_not_phone_and_escalates_late(self):
        notes = []
        with mock.patch.object(web_steward, "notify_phone", lambda text, click="", title="": notes.append(text) or True):
            res = web_steward._apply(sw.Action("ask_user", "a", "STEWARD-ROUTINE",
                                               {"project": "a", "text": "Şimdi mi açalım?", "routine": True}),
                                     steward_cfg(), sw.load_projects())
            self.assertTrue(res["ok"] and res["routine"] and not res["notified"])
            self.assertEqual(notes, [])
            q = sw.open_questions()[0]
            self.assertTrue(q.routine)
            cfg = _cfg(max_active=4)
            projects = {"a": sw.Project(name="a", phase="planned", cadence_minutes=60)}
            items = sw.review_items([], projects, cfg, q.created_at + 60, [q], [])
            self.assertEqual([(i["kind"], i["id"]) for i in items], [("routine", q.id)])
            self.assertIn("steward_answer", sw.build_tour_prompt(items, "tr", sw.open_questions()))
            acts, _ = sw.plan_tick([], projects, {}, cfg, q.created_at + 60, [q], [])
            self.assertEqual([a.kind for a in acts if a.kind == "escalate_routine"], [])
            acts, _ = sw.plan_tick([], projects, {}, cfg, q.created_at + sw.ROUTINE_ESCALATE_SECONDS + 1, [q], [])
            esc = [a for a in acts if a.kind == "escalate_routine"]
            self.assertEqual(len(esc), 1)
            res = web_steward._apply(esc[0], steward_cfg(), sw.load_projects())
            self.assertTrue(res["ok"] and res["notified"])
            self.assertEqual(len(notes), 1)
            self.assertFalse(sw.find_question(q.id).routine)

    def test_brain_answer_is_delivered_like_any_answer(self):
        q = sw.add_question("a", "Şimdi mi açalım?", source="a", routine=True)
        sw.answer_question(q.id, "Evet, devir notuyla aç")
        self.assertEqual([x.id for x in sw.undelivered_answers()], [q.id])


class OneLiveSessionPerProjectTest(_Tmp):
    def test_finished_handover_of_second_session_stops_it_instead_of_respawn(self):
        cfg = _cfg(max_active=4)
        projects = {"ncs": sw.Project(name="ncs", phase="planned", cadence_minutes=60)}
        a = _view("ncs", busy=False, last_assistant="devir\nREADY FOR HANDOVER")
        b = _view("ncs20261019", blueprint="ncs", busy=True)
        acts, st = sw.plan_tick([a, b], projects, {"ho_pending": {"ncs": 1000.0}}, cfg, 2000.0, [], [])
        mine = [(x.kind, x.name) for x in acts if x.name == "ncs"]
        self.assertEqual(mine, [("stop", "ncs")])
        self.assertNotIn("ncs", st["ho_pending"])
        # tek oturum kaldıysa eskisi gibi yeniden açılır
        acts, _ = sw.plan_tick([a], projects, {"ho_pending": {"ncs": 1000.0}}, cfg, 2000.0, [], [])
        self.assertEqual([(x.kind, x.name) for x in acts if x.name == "ncs"], [("respawn", "ncs")])

    def test_economy_rules_only_touch_managed_sessions(self):
        cfg = _cfg(max_active=4, context_warn_tokens=300000)
        projects = {"ncs": sw.Project(name="ncs", phase="planned", cadence_minutes=60)}
        other = _view("egyptian20260917", busy=False, history_size=1990, context_tokens=700000)
        mine = _view("ncs20261019", blueprint="ncs", busy=True, history_size=10, context_tokens=700000)
        brain = _view("degnekci", busy=False, history_size=1950)
        acts, st = sw.plan_tick([other, mine, brain], projects, {}, cfg, 5000.0, [], [])
        self.assertEqual(sorted(x.name for x in acts if x.kind == "handover"), ["degnekci", "ncs20261019"])
        # eski kayıttaki yönetilmeyen ho_pending: yeniden açma yok, kayıt temizlenir
        acts, st = sw.plan_tick([other], projects, {"ho_pending": {"egyptian20260917": 1000.0}}, cfg, 99999.0, [], [])
        self.assertEqual([x for x in acts if x.name == "egyptian20260917"], [])
        self.assertNotIn("egyptian20260917", st["ho_pending"])

    def test_brain_respawn_after_handover_is_a_new_conversation(self):
        calls = []
        cfg = steward_cfg()
        with mock.patch.object(web_steward, "_running", lambda n: None), \
                mock.patch.object(web_steward, "brain_start", lambda c=None, fresh=False: calls.append(fresh) or {"ok": True}):
            web_steward._apply(sw.Action("respawn", cfg.brain_name, "READY FOR HANDOVER"), cfg, {})
        self.assertEqual(calls, [True])

    def test_context_tokens_trigger_handover(self):
        cfg = _cfg(max_active=4, context_warn_tokens=300000)
        projects = {"a": sw.Project(name="a", phase="planned", cadence_minutes=60)}
        big = _view("a", busy=True, history_size=10, context_tokens=410000)
        acts, st = sw.plan_tick([big], projects, {}, cfg, 5000.0, [], [])
        ho = [x for x in acts if x.kind == "handover"]
        self.assertEqual([x.name for x in ho], ["a"])
        self.assertIn("token", ho[0].reason)
        small = _view("a", busy=True, history_size=10, context_tokens=120000)
        acts, _ = sw.plan_tick([small], projects, {}, cfg, 5000.0, [], [])
        self.assertEqual([x for x in acts if x.kind == "handover"], [])
        off = _cfg(max_active=4, context_warn_tokens=0)
        acts, _ = sw.plan_tick([big], projects, {}, off, 5000.0, [], [])
        self.assertEqual([x for x in acts if x.kind == "handover"], [])

    def test_line_count_is_only_a_fallback_and_ignores_young_sessions(self):
        projects = {"a": sw.Project(name="a", phase="planned", cadence_minutes=60)}
        cfg = _cfg(max_active=4, context_warn_tokens=300000, history_warn_at=1900, history_min_age_minutes=15)
        now = 100000.0
        # token biliniyor ve küçük: satır sayısı ne olursa olsun devir yok
        known = _view("a", busy=False, history_size=1990, context_tokens=120000, started_at=now - 3600)
        acts, _ = sw.plan_tick([known], projects, {}, cfg, now, [], [])
        self.assertEqual([x for x in acts if x.kind == "handover"], [])
        # token bilinmiyor + satır dolu ama oturum yeni açıldı (7 dk): devir yok
        young = _view("a", busy=False, history_size=1990, context_tokens=None, started_at=now - 7 * 60)
        acts, _ = sw.plan_tick([young], projects, {}, cfg, now, [], [])
        self.assertEqual([x for x in acts if x.kind == "handover"], [])
        # token bilinmiyor + satır dolu + yaşlı oturum: yedek ölçüt devreye girer
        old = _view("a", busy=False, history_size=1990, context_tokens=None, started_at=now - 40 * 60)
        acts, _ = sw.plan_tick([old], projects, {}, cfg, now, [], [])
        ho = [x for x in acts if x.kind == "handover"]
        self.assertEqual([x.name for x in ho], ["a"])
        self.assertIn("history_size", ho[0].reason)
        # yaş koruması kapalı (0): yeni oturum da devreder
        nocfg = _cfg(max_active=4, context_warn_tokens=300000, history_warn_at=1900, history_min_age_minutes=0)
        acts, _ = sw.plan_tick([young], projects, {}, nocfg, now, [], [])
        self.assertEqual([x.name for x in acts if x.kind == "handover"], ["a"])

    def test_workspace_claude_md_carries_the_permanent_model_rule(self):
        for lang, needle in (("tr", "Sonnet 5.5 + medium"), ("en", "Sonnet 5.5 + medium")):
            text = sw.build_workspace_claude_md("persona", lang=lang)
            self.assertIn(needle, text)
            self.assertIn("Fable", text)
        self.assertEqual(sw.Config().planning_effort, "medium")
        self.assertIn("İSTİSNA", sw.build_workspace_claude_md("p", lang="tr"))
        self.assertIn("EXCEPTION", sw.build_workspace_claude_md("p", lang="en"))

    def test_fable_sessions_use_the_lower_context_threshold(self):
        projects = {"a": sw.Project(name="a", phase="planned", cadence_minutes=60)}
        cfg = _cfg(max_active=4, context_warn_tokens=300000, context_warn_tokens_fable=150000)
        fable = _view("a", busy=True, history_size=10, context_tokens=200000, model="claude-fable-5-1")
        acts, _ = sw.plan_tick([fable], projects, {}, cfg, 5000.0, [], [])
        ho = [x for x in acts if x.kind == "handover"]
        self.assertEqual([x.name for x in ho], ["a"])
        self.assertIn("150000", ho[0].reason)
        sonnet = _view("a", busy=True, history_size=10, context_tokens=200000, model="claude-sonnet-5-5")
        acts, _ = sw.plan_tick([sonnet], projects, {}, cfg, 5000.0, [], [])
        self.assertEqual([x for x in acts if x.kind == "handover"], [])
        # Fable eşiği 0: genel eşik (300K) geçerli
        off = _cfg(max_active=4, context_warn_tokens=300000, context_warn_tokens_fable=0)
        acts, _ = sw.plan_tick([fable], projects, {}, off, 5000.0, [], [])
        self.assertEqual([x for x in acts if x.kind == "handover"], [])

    def test_context_tokens_from_transcript_tail(self):
        import json as _json
        d = os.path.join(self.dir.name, "t")
        os.makedirs(d)
        path = os.path.join(d, "s.jsonl")
        with open(path, "w") as f:
            f.write(_json.dumps({"message": {"role": "assistant", "usage": {"input_tokens": 3, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 50}}}) + "\n")
            f.write(_json.dumps({"message": {"role": "user", "content": "x"}}) + "\n")
            f.write(_json.dumps({"message": {"role": "assistant", "usage": {"input_tokens": 5, "cache_read_input_tokens": 400000, "cache_creation_input_tokens": 200}}}) + "\n")
        with mock.patch("claudeops.providers.claude_provider.jsonl_path_for", lambda cwd, sid: path):
            self.assertEqual(web_steward.context_tokens_for("/x", "sid"), 400205)
        with mock.patch("claudeops.providers.claude_provider.jsonl_path_for", lambda cwd, sid: None):
            self.assertIsNone(web_steward.context_tokens_for("/x", "sid"))
        # sid bilinmiyorsa mtime tahmini YOK: başka konuşmanın transkripti sahte eşik aşımı üretmişti
        with mock.patch("claudeops.providers.claude_provider.jsonl_path_for", lambda cwd, sid: path):
            self.assertIsNone(web_steward.context_tokens_for("/x", None))


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


class StuckBrainTest(_Tmp):
    def test_status_sentence_is_not_a_routine_question_and_tour_is_capped(self):
        cfg = _cfg(max_active=4)
        projects = {"a": sw.Project(name="a", phase="planned", cadence_minutes=60)}
        v = _view("a", last_assistant="STEWARD-ROUTINE: Paket 4a bitene kadar bekliyorum, yeni soru yok.")
        acts, _ = sw.plan_tick([v], projects, {}, cfg, 5000.0, [], [])
        self.assertEqual([a for a in acts if a.reason == "STEWARD-ROUTINE"], [])
        ideas = [sw.Idea(id=f"i{n}", text="t", created_at=0) for n in range(sw.TOUR_MAX_ITEMS + 5)]
        brain = _view("degnekci", busy=False)
        acts, st = sw.plan_tick([brain], projects, {}, _cfg(tour_minutes=1), 99999.0, [], ideas)
        tour = [a for a in acts if a.kind == "tour"]
        self.assertEqual(len(tour), 1)
        self.assertEqual(len(tour[0].payload["items"]), sw.TOUR_MAX_ITEMS)

    def test_two_failed_tours_restart_the_brain(self):
        cfg = steward_cfg()
        restarted = []
        with mock.patch.object(web_steward, "run_tour", lambda items=None, force=False: {"ok": False, "error": "send failed"}), \
                mock.patch.object(web_steward, "brain_restart_for_stuck_input", lambda c: restarted.append(1) or {"ok": True}):
            r1 = web_steward._apply(sw.Action("tour", "degnekci", "t", {"items": []}), cfg, {})
            self.assertFalse(r1["ok"])
            self.assertEqual((restarted, sw.load_state().get("tour_fail")), ([], 1))
            web_steward._apply(sw.Action("tour", "degnekci", "t", {"items": []}), cfg, {})
            self.assertEqual((restarted, sw.load_state().get("tour_fail")), ([1], 0))
        with mock.patch.object(web_steward, "run_tour", lambda items=None, force=False: {"ok": True}):
            sw.save_state({"tour_fail": 1})
            web_steward._apply(sw.Action("tour", "degnekci", "t", {"items": []}), cfg, {})
            self.assertEqual(sw.load_state().get("tour_fail"), 0)

    def test_undeliverable_adhoc_answer_is_given_up(self):
        q = sw.add_question("zk_x", "?", source="zk_x")
        sw.answer_question(q.id, "A")
        with mock.patch.object(web_steward, "_give_directive", lambda *a, **k: {"ok": False, "error": "send failed"}):
            res = web_steward._apply(sw.Action("deliver_answer", "zk_x", "answer", {"question_id": q.id}), steward_cfg(), {})
        self.assertFalse(res["ok"])
        self.assertEqual(sw.undelivered_answers(), [])


class DeliveryTargetTest(_Tmp):
    def test_prefers_asking_session_then_main_over_experiment_sessions(self):
        V = lambda n: sw.SessionView(name=n, running=True, blueprint="wifi5gppr")
        views = [V("wifi5gppr20261016_2"), V("wifi5gppr20261019"), V("wifi5gppr20261016_5")]
        self.assertEqual(sw.pick_delivery_view(views, "wifi5gppr", "wifi5gppr20261016_5").name, "wifi5gppr20261016_5")
        self.assertEqual(sw.pick_delivery_view(views, "wifi5gppr", "").name, "wifi5gppr20261019")
        self.assertEqual(sw.pick_delivery_view(views, "wifi5gppr", "kapali").name, "wifi5gppr20261019")
        self.assertIsNone(sw.pick_delivery_view(views, "baska", ""))
        views[0].running = False
        self.assertEqual(sw.pick_delivery_view(views, "wifi5gppr", "wifi5gppr20261016_2").name, "wifi5gppr20261019")


class ReaskTest(_Tmp):
    def _answered(self, project, text, answer, ago=60.0):
        q = sw.add_question(project, text)
        sw.answer_question(q.id, answer)
        qs = sw.load_questions()
        for x in qs:
            if x.id == q.id:
                x.answered_at = sw._now() - ago
                x.delivered_at = sw._now() - ago
        sw.save_questions(qs)
        return q

    def test_similar_answered_question_is_redelivered_not_reopened(self):
        q = self._answered("zlkrn", "Sıradaki iş Urdu Âzâd kalan sayfaları mı olsun yoksa Aşama 2 mi", "ikisi de")
        again = sw.add_question("zlkrn", "Sıradaki iş Urdu Âzâd'ın kalan sayfaları mı olsun, yoksa Aşama 2'ye mi geçelim")
        self.assertEqual(again.id, q.id)
        self.assertEqual(sw.find_question(q.id).repeats, 1)
        self.assertEqual([x.id for x in sw.undelivered_answers()], [q.id])
        self.assertEqual(sw.open_questions(), [])
        msg = sw.build_directive(sw.Project(name="zlkrn"), answer=sw.find_question(q.id))
        self.assertIn("zaten cevapladım", msg)

    def test_repeat_cap_other_project_old_and_clarification_open_new(self):
        q = self._answered("zlkrn", "Urdu Âzâd kalan sayfaları mı olsun", "ikisi de")
        for _ in range(sw.REASK_MAX_REPEATS):
            self.assertEqual(sw.add_question("zlkrn", "Urdu Âzâd kalan sayfaları mı olsun").id, q.id)
        self.assertNotEqual(sw.add_question("zlkrn", "Urdu Âzâd kalan sayfaları mı olsun").id, q.id)   # sınır aşıldı
        self.assertNotEqual(sw.add_question("ncs", "Urdu Âzâd kalan sayfaları mı olsun").id, q.id)      # başka proje
        old = self._answered("mkt", "Beck PDF import edilsin mi", "evet", ago=sw.REASK_WINDOW_SECONDS + 10)
        self.assertNotEqual(sw.add_question("mkt", "Beck PDF import edilsin mi").id, old.id)             # eski
        unclear = self._answered("wifi", "GSA satırı parça düzeyi mi katı kural mı", "anlamadim detayli sor")
        self.assertNotEqual(sw.add_question("wifi", "GSA satırı parça düzeyi mi katı kural mı").id, unclear.id)

    def test_directive_lists_earlier_answers(self):
        a = self._answered("zlkrn", "Birinci soru burada", "sıradan git", ago=300)
        b = self._answered("zlkrn", "İkinci farklı soru metni", "ikisi de", ago=100)
        msg = sw.build_directive(sw.Project(name="zlkrn"), answer=sw.find_question(b.id))
        self.assertIn("Önceki cevaplarım", msg)
        self.assertIn("sıradan git", msg)
        self.assertNotIn("zaten cevapladım", msg)
        self.assertIn("KALICI kuraldır", msg)


class QuestionOptionsTest(_Tmp):
    def test_options_normalize_resolve_and_key(self):
        self.assertEqual(sw.normalize_options(["  evet ", "hayır", "evet", "", None, 3, True]), ["evet", "hayır", "3"])
        self.assertEqual(sw.normalize_options("tek"), ["tek"])
        self.assertEqual(sw.normalize_options(None), [])
        self.assertEqual(len(sw.normalize_options([str(i) for i in range(10)])), sw.QUESTION_MAX_OPTIONS)
        self.assertEqual(len(sw.normalize_options(["x" * 500])[0]), sw._MAX_OPTION_CHARS)
        q = sw.add_question("kitap", "A mı B mi?", source="brain", options=["A", "B", "sonra"])
        self.assertEqual(q.options, ["A", "B", "sonra"])
        self.assertEqual(len(q.key), 16)
        self.assertEqual(sw.add_question("kitap", "A mı B mi?").key, q.key)            # dedup aynı kaydı döner
        for raw, want in (("2", "B"), ("b", "B"), ("SONRA", "sonra"), ("C", "sonra"), ("0", "0"), ("başka şey", "başka şey"),
                          ("  A  ", "A")):
            self.assertEqual(sw.resolve_answer(q, raw), want, raw)
        self.assertEqual(sw.resolve_answer(sw.Question("x", "", "s", 0.0), "1"), "1")   # seçeneksiz: metin olduğu gibi
        self.assertEqual(sw.answer_question(q.id, "3").answer, "sonra")
        self.assertEqual(sw.find_question(q.id).status, "answered")
        self.assertIsNone(sw.find_question("yok"))
        # eski kayıt (options/key/notified_at alanları yok) sorunsuz yüklenir
        sw.save_questions([])
        with open(sw.QUESTIONS_JSON, "w", encoding="utf-8") as f:
            json.dump([{"id": "q_old", "project": "p", "text": "eski?", "created_at": 1.0}], f)
        old = sw.load_questions()[0]
        self.assertEqual((old.options, old.key, old.notified_at), ([], "", 0.0))
        self.assertEqual(sw.question_link(old, "https://t.example"), "")              # anahtarsız: bağlantı yok
        self.assertEqual(sw.question_link(q, "https://t.example/"), f"https://t.example/q/{q.id}?k={q.key}")
        self.assertEqual(sw.question_link(q, ""), "")
        sw.mark_notified(old.id)
        self.assertGreater(sw.load_questions()[0].notified_at, 0)

    def test_notification_text_and_page_html(self):
        q = sw.Question("q1", "kitap", "A <b>mı</b> B mi?", 1_700_000_000.0, source="brain", options=["A", "B & C"], key="k1")
        txt = sw.question_notification(q, "https://t/q/q1?k=k1", "tr")
        self.assertEqual(txt.splitlines(), ["[kitap] A <b>mı</b> B mi?", "1) A", "2) B & C", "→ cevapla: https://t/q/q1?k=k1"])
        self.assertIn("py/cops steward answer q1", sw.question_notification(q, "", "en"))
        page = sw.question_page_html(q, "tr", "ask", action="/q/q1?k=k1")
        self.assertIn("A &lt;b&gt;mı&lt;/b&gt; B mi?", page)                        # kaçışlı
        self.assertNotIn("<b>mı</b>", page)
        self.assertIn("value='B &amp; C'", page)
        self.assertEqual(page.count("class='opt'"), 2)
        self.assertIn("method='post' action='/q/q1?k=k1'", page)
        self.assertIn("viewport", page)
        self.assertNotIn("<script", page)
        q.answer, q.status = "B & C", "answered"
        done = sw.question_page_html(q, "en", "done")
        self.assertIn("Answer saved", done)
        self.assertIn("→ B &amp; C", done)
        self.assertNotIn("<form", done)
        self.assertIn("already answered", sw.question_page_html(q, "en", "already"))
        self.assertIn("Böyle bir soru yok", sw.question_page_html(None, "tr", "missing"))
        self.assertIn("Invalid link", sw.question_page_html(None, "en", "denied"))
        self.assertIn("Boş cevap", sw.question_page_html(q, "tr", "ask", error="Boş cevap gönderilemez"))


class SettingsTest(_Tmp):
    def test_defaults_parse_and_clamp(self):
        cfg = settings.steward_config()
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.history_warn_at, 1900)
        settings.save_settings({"steward": {"enabled": "on", "tick_seconds": "5", "max_active": "abc", "lang": "xx",
                                            "brain_name": "bad name"}, "history_warn_at": 1500})
        cfg = settings.steward_config()
        self.assertTrue(cfg.enabled)
        self.assertEqual((cfg.tick_seconds, cfg.max_active, cfg.lang, cfg.brain_name, cfg.history_warn_at),
                         (15, 4, "tr", "degnekci", 1500))
        self.assertEqual((cfg.mode, cfg.summary_hour), ("observe", 21))            # varsayılan: observe
        settings.save_settings({"steward": {"mode": "act", "summary_hour": "99"}})
        cfg = settings.steward_config()
        self.assertEqual((cfg.mode, cfg.summary_hour), ("act", 23))
        settings.save_settings({"steward": {"mode": "yolo", "card_refresh": "off", "cards_per_tick": "3"}})
        cfg = settings.steward_config()
        self.assertEqual((cfg.mode, cfg.card_refresh, cfg.cards_per_tick), ("observe", False, 3))   # bilinmeyen kip = observe
        settings.save_settings({"steward": {"enabled": ""}})   # boş = varsayılana dön
        self.assertFalse(settings.steward_config().enabled)
        self.assertNotIn("enabled", settings.load_settings()["steward"])


class McpTest(unittest.TestCase):
    def test_tools_list_and_dispatch_cover_each_other(self):
        self.assertEqual({t["name"] for t in mcp_steward.TOOLS}, set(mcp_steward.DISPATCH))
        reply = mcp_queue._handle(8765, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                  mcp_steward.TOOLS, mcp_steward.DISPATCH, mcp_steward.SERVER_NAME)
        self.assertEqual(len(reply["result"]["tools"]), len(mcp_steward.TOOLS))
        init = mcp_queue._handle(8765, {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
                                 mcp_steward.TOOLS, mcp_steward.DISPATCH, mcp_steward.SERVER_NAME)
        self.assertEqual(init["result"]["serverInfo"]["name"], "cops-steward")
        # eski mcp-queue davranışı değişmedi
        old = mcp_queue._handle(8765, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        self.assertEqual({t["name"] for t in old["result"]["tools"]}, set(mcp_queue.DISPATCH))

    def test_tool_calls_hit_expected_endpoints(self):
        calls = []

        def fake_api(port, method, path, body=None):
            calls.append((method, path, body))
            return {"ok": True}

        with mock.patch.object(mcp_queue, "_api", fake_api):
            mcp_steward._directive(1, {"name": "p", "text": "yap", "model": "m"})
            mcp_steward._restart(1, {"name": "p", "directive": "d", "reason": "boş iş"})
            mcp_steward._ask(1, {"project": "p", "question": "?"})
            mcp_steward._context(1, {"name": "p"})
            self.assertEqual(mcp_steward._directive(1, {"name": "p"})["ok"], False)
        self.assertEqual(calls[0][:2], ("POST", "/api/steward/directive"))
        self.assertEqual(calls[0][2]["model"], "m")
        self.assertTrue(calls[0][2]["start_if_stopped"])
        self.assertEqual(calls[1][2]["text"], "d")
        self.assertEqual(calls[2][2]["text"], "?")
        self.assertEqual(calls[3][:2], ("GET", "/api/steward/context?name=p"))


class HttpTest(_Tmp):
    def setUp(self):
        super().setUp()
        # tick_once kart adımını arka plan thread'inde koşturur: bir sonraki test `_CARD_LOCK`u tutulu bulup
        # kartı hiç üretmiyordu (dosya bütün koşunca kırılan flaky test). Testlerde iş satır içi koşsun.
        bg = mock.patch.object(web_steward, "_CARD_BACKGROUND", False)
        bg.start()
        self.addCleanup(bg.stop)
        self.calls = []
        self.fleet = {}

        def start(name, model="", effort="", fresh=False, lang="tr"):
            self.calls.append(("start", name, model, effort))
            return {"ok": True}

        def stop(name, lang="tr"):
            self.calls.append(("stop", name))
            return {"ok": True}

        def handover(name, lang="tr"):
            self.calls.append(("handover", name))
            return {"ok": True}

        def register(name, cwd, model="", cli="", lang="tr"):
            self.calls.append(("register", name, cwd))
            self.fleet[name] = {"cwd": cwd, "model": model, "cli": cli or "claude", "state": "active"}
            return {"ok": True}

        web_steward.configure(status_payload=lambda: {"sessions": []}, fleet_status=lambda: self.fleet,
                              start=start, stop=stop, handover=handover, register_project=register)
        web_steward._RECENT.clear()

    def _export_env(self, names=("zlkrn", "mkt")):
        cwds = {}
        for n in names:
            d = os.path.join(self.dir.name, n)
            os.makedirs(d)
            cwds[n] = d
            self.fleet[n] = {"cwd": d, "model": "", "cli": "claude", "state": "active"}
            sw.upsert_project(n, phase="planned")
        return cwds

    def test_idea_export_project_todo_hides_idea_and_keeps_record(self):
        cwds = self._export_env()
        i = web_steward.http_post("/api/steward/idea", {"text": "Nüvayrî\nlistesi bak", "source": "zlkrn20261018"})["idea"]
        r = web_steward.http_post("/api/steward/idea/export", {"id": i["id"], "kind": "todo", "target": "project"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["written"], ["zlkrn"])
        todo = Path(os.path.join(cwds["zlkrn"], "TODO.md")).read_text(encoding="utf-8")
        self.assertIn("## Değnekçi fikirleri", todo)
        self.assertIn(f"- [ ] (değnekçi fikri {i['id']}) Nüvayrî listesi bak", todo)      # satır sonu tek satıra iner
        self.assertFalse(os.path.exists(os.path.join(cwds["mkt"], "TODO.md")))
        self.assertEqual(web_steward.http_get("/api/steward/ideas", {})["ideas"], [])        # varsayılan (new) listeden kalktı
        kept = web_steward.http_get("/api/steward/ideas", {"status": ["exported"]})["ideas"]
        self.assertEqual(kept[0]["exported"][0]["projects"], ["zlkrn"])                      # kayıt fikrin üstünde duruyor

    def test_idea_export_all_tbd_and_idempotent(self):
        cwds = self._export_env()
        i = web_steward.http_post("/api/steward/idea", {"text": "genel fikir"})["idea"]
        r = web_steward.http_post("/api/steward/idea/export", {"id": i["id"], "kind": "tbd", "target": "all"})
        self.assertEqual(sorted(r["written"]), ["mkt", "zlkrn"])
        r2 = web_steward.http_post("/api/steward/idea/export", {"id": i["id"], "kind": "tbd", "target": "all"})
        self.assertEqual((r2["written"], sorted(r2["already"])), ([], ["mkt", "zlkrn"]))
        for d in cwds.values():
            self.assertEqual(Path(os.path.join(d, "TOBEDECIDED.md")).read_text(encoding="utf-8").count(i["id"]), 1)

    def test_idea_export_appends_under_existing_heading_and_validates(self):
        cwds = self._export_env(("zlkrn",))
        a = web_steward.http_post("/api/steward/idea", {"text": "bir", "source": "zlkrn20261018"})["idea"]
        b = web_steward.http_post("/api/steward/idea", {"text": "iki", "source": "zlkrn"})["idea"]
        for x in (a, b):
            self.assertTrue(web_steward.http_post("/api/steward/idea/export", {"id": x["id"], "kind": "todo"})["ok"])
        todo = Path(os.path.join(cwds["zlkrn"], "TODO.md")).read_text(encoding="utf-8")
        self.assertEqual(todo.count("## Değnekçi fikirleri"), 1)                             # ikinci madde aynı başlığın altına
        # Kimlikte TEK proje varsa projesiz fikir ona gider (kullanıcı kararı 2026-10-21)
        one = web_steward.http_post("/api/steward/idea", {"text": "tek proje"})["idea"]
        r1 = web_steward.http_post("/api/steward/idea/export", {"id": one["id"], "kind": "todo"})
        self.assertTrue(r1["ok"] and r1["written"] == ["zlkrn"], r1)
        # ... birden çok proje varsa belirsizdir: reddedilir (target=all seçilmeli)
        sw.upsert_project("mkt2", phase="planned")
        c = web_steward.http_post("/api/steward/idea", {"text": "sahipsiz"})["idea"]
        self.assertFalse(web_steward.http_post("/api/steward/idea/export", {"id": c["id"], "kind": "todo"})["ok"])   # projesiz + target=project
        self.assertFalse(web_steward.http_post("/api/steward/idea/export", {"id": c["id"], "kind": "x"})["ok"])
        self.assertFalse(web_steward.http_post("/api/steward/idea/export", {"id": "yok", "kind": "todo", "target": "all"})["ok"])
        self.assertEqual(web_steward.http_get("/api/steward/ideas", {})["ideas"][0]["id"], c["id"])           # başarısız aktarım fikri saklamaz

    def test_running_names_resolve_digit_in_project_name(self):
        """`Session.base` rakamlı proje adını (wifi5gppr) çözemez: oturum yine de o projenin çalıştığını göstermeli."""
        from types import SimpleNamespace as NS
        for n in ("wifi5gppr", "ncs"):
            sw.upsert_project(n, phase="planned")
        live = [NS(name="wifi5gppr20261019", base="wifi5gppr20261019"), NS(name="wifi5gppr20261016_2", base="wifi5gppr20261016_2"),
                NS(name="ncs20261019", base="ncs")]
        got = web_steward._running_names_for(live, sw.load_projects())
        self.assertIn("wifi5gppr", got)
        self.assertIn("ncs", got)
        self.assertNotIn("zzz", got)
        self.assertEqual(web_steward._running_names_for([], sw.load_projects()), set())

    def test_project_ask_answer_idea_note(self):
        r = web_steward.http_post("/api/steward/project", {"name": "p", "phase": "planning", "goal": "g", "priority": 2})
        self.assertTrue(r["ok"])
        self.assertEqual(r["project"]["priority"], 2)
        self.assertFalse(web_steward.http_post("/api/steward/project", {"name": "Bad"})["ok"])
        r = web_steward.http_post("/api/steward/ask", {"project": "p", "text": "A mı B mi?", "source": "t"})
        self.assertTrue(r["ok"] and not r["notified"])
        self.assertEqual(len(web_steward.http_get("/api/steward/questions", {})["questions"]), 1)
        self.assertTrue(web_steward.http_post("/api/steward/answer", {"id": r["id"], "answer": "A"})["ok"])
        self.assertFalse(web_steward.http_post("/api/steward/answer", {"id": "x", "answer": "A"})["ok"])
        i = web_steward.http_post("/api/steward/idea", {"text": "fikir"})
        self.assertEqual(web_steward.http_post("/api/steward/idea", {"id": i["idea"]["id"], "status": "later"})["idea"]["status"], "later")
        self.assertTrue(web_steward.http_post("/api/steward/note", {"project": "p", "text": "n"})["ok"])
        self.assertFalse(web_steward.http_post("/api/steward/note", {"project": "zzz", "text": "n"})["ok"])
        self.assertEqual(web_steward.http_get("/api/steward/projects", {})["projects"][0]["notes"], "n")
        self.assertIsNone(web_steward.http_get("/api/steward/nope", {}))
        self.assertIsNone(web_steward.http_post("/api/steward/nope", {}))
        state = web_steward.http_get("/api/steward/state", {})
        self.assertEqual(state["summary"]["projects"]["planning"], 1)
        self.assertEqual(len(web_steward.http_get("/api/steward/log", {"n": ["100"]})["entries"]), 6)

    def test_ask_with_options_notifies_with_link_once(self):
        notes = []
        with open(web_steward.TUNNEL_URL_FILE, "w", encoding="utf-8") as f:
            f.write("https://tun.example.com\n")
        with mock.patch.object(web_steward, "notify_phone", lambda text, click="", title="": notes.append((text, click)) or True):
            r = web_steward.http_post("/api/steward/ask", {"project": "p", "text": "A mı B mi?", "options": ["A", "B"], "source": "t"})
            self.assertTrue(r["ok"] and r["notified"])
            self.assertEqual(r["link"], f"https://tun.example.com/q/{r['id']}?k={sw.find_question(r['id']).key}")
            self.assertEqual(notes[0][1], r["link"])                                  # ntfy Click başlığı = sayfa
            self.assertIn("1) A\n2) B\n→ cevapla: https://tun.example.com/q/", notes[0][0])
            again = web_steward.http_post("/api/steward/ask", {"project": "p", "text": "A mı B mi?"})
        self.assertEqual((again["id"], again["notified"], again.get("dup")), (r["id"], False, True))   # ikinci bildirim yok
        self.assertEqual(len(notes), 1)
        self.assertEqual(web_steward.http_get("/api/steward/questions", {})["questions"][0]["options"], ["A", "B"])
        self.assertTrue(web_steward.http_post("/api/steward/answer", {"id": r["id"], "answer": "2"})["ok"])
        self.assertEqual(sw.find_question(r["id"]).answer, "B")
        os.remove(web_steward.TUNNEL_URL_FILE)
        with mock.patch.object(web_steward, "notify_phone", lambda text, click="", title="": notes.append((text, click)) or False):
            r2 = web_steward.http_post("/api/steward/ask", {"project": "p", "text": "tünelsiz?"})
        self.assertEqual((r2["link"], r2["notified"]), ("", False))
        self.assertEqual(notes[-1][1], "")
        self.assertIn("py/cops steward answer", notes[-1][0])
        self.assertEqual(sw.find_question(r2["id"]).notified_at, 0.0)                 # ntfy yoksa işaretlenmez

    def test_question_page_auth_and_answer_flow(self):
        q = sw.add_question("p", "Devam mı?", options=["evet", "hayır"])
        page = lambda key="", token=False, form=None: web_steward.http_question_page(q.id, key, token, form)  # noqa: E731
        self.assertEqual(web_steward.http_question_page("yok", q.key, True)[0], 404)
        self.assertEqual(page()[0], 401)
        self.assertEqual(page("yanlış")[0], 401)
        status, html_text = page(q.key)
        self.assertEqual(status, 200)
        self.assertIn("value='evet'", html_text)
        self.assertIn(f"action='/q/{q.id}?k={q.key}'", html_text)
        self.assertEqual(page("", token=True)[0], 200)                                # panel token'ı da yeter
        status, html_text = page(q.key, form={"answer": ""})
        self.assertEqual(status, 400)
        self.assertIn("Boş cevap", html_text)
        self.assertEqual(sw.find_question(q.id).status, "open")
        with mock.patch.object(web_steward.web_ws, "notify_status_changed", lambda: None):
            status, html_text = page(q.key, form={"answer": "2"})
        self.assertEqual(status, 200)
        self.assertIn("Cevap kaydedildi", html_text)
        self.assertIn("→ hayır", html_text)
        self.assertEqual(sw.find_question(q.id).answer, "hayır")
        self.assertTrue(any(e["event"] == "answer" and e.get("source") == "phone" for e in sw.tail_log(10)))
        status, html_text = page(q.key)                                               # tekrar açınca: zaten cevaplanmış
        self.assertEqual(status, 200)
        self.assertIn("zaten cevaplanmış", html_text)
        self.assertNotIn("<form", html_text)
        self.assertEqual(page(q.key, form={"answer": "evet"})[1].count("→ hayır"), 1)   # ikinci POST cevabı değiştirmez

    def test_register_creates_folder_goal_and_roster(self):
        cwd = os.path.join(self.dir.name, "proj")
        src = os.path.join(self.dir.name, "kaynak.pdf")
        with open(src, "w") as f:
            f.write("x")
        r = web_steward.http_post("/api/steward/register",
                                  {"name": "yeni", "cwd": cwd, "goal": "bir makale", "kind": "article",
                                   "resources": [src, "https://example.org/paper"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["copied"], ["kaynak.pdf"])
        self.assertTrue(os.path.isfile(os.path.join(cwd, "kaynaklar", "kaynak.pdf")))
        with open(os.path.join(cwd, "GOAL.md"), encoding="utf-8") as f:
            goal = f.read()
        self.assertIn("bir makale", goal)
        self.assertIn("https://example.org/paper", goal)
        self.assertEqual(self.calls[-1][:2], ("register", "yeni"))
        self.assertEqual(sw.load_projects()["yeni"].phase, "planning")
        ctx = web_steward.http_get("/api/steward/context", {"name": ["yeni"]})
        self.assertIn("GOAL.md", ctx["docs"])
        self.assertTrue(web_steward.http_get("/api/steward/file", {"name": ["yeni"], "path": ["GOAL.md"]})["ok"])
        self.assertFalse(web_steward.http_get("/api/steward/file", {"name": ["yeni"], "path": ["../x"]})["ok"])
        self.assertFalse(web_steward.http_post("/api/steward/register", {"name": "x", "cwd": "rel/path", "goal": "g"})["ok"])

    def test_tick_applies_actions_with_mocked_views(self):
        sw.upsert_project("a", phase="planned", cadence_minutes=60)
        settings.save_settings({"steward": {"enabled": "on", "mode": "act"}})
        views = [_view("a", running=False)]
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: views), \
                mock.patch.object(web_steward, "_running", lambda name: None), \
                mock.patch.object(web_steward, "_ensure_running", lambda name, **kw: {"ok": False, "error": "no tmux here"}):
            res = web_steward.tick_once("test")
        self.assertTrue(res["ok"])
        self.assertEqual([(a["kind"], a["name"], a["ok"]) for a in res["actions"]], [("start", "a", False)])
        self.assertEqual(web_steward._RECENT[0]["detail"], "no tmux here")
        self.assertEqual(sw.load_state()["last_directive_at"]["a"], res["at"])

    # ── proje kartları (motor) ──────────────────────────────────────────────

    def _card_env(self, **docs):
        """Çalışmayan, planned bir proje + gerçek git deposu; model çağrısı sahte."""
        cwd = _make_repo(os.path.join(self.dir.name, "kitap"), **(docs or {"GOAL.md": "# amaç\nKitap", "TODO.md": "- bölüm 3"}))
        self.fleet["kitap"] = {"cwd": cwd, "model": "", "cli": "claude", "state": "active"}
        sw.upsert_project("kitap", phase="planned", goal="Kitap yaz", priority=2)
        self.oneshot_calls = []
        self.oneshot_reply = GOOD_JSON

        def fake_oneshot(prov_self, prompt, model, cwd_, timeout=120.0):
            self.oneshot_calls.append((prompt, model, cwd_))
            if isinstance(self.oneshot_reply, Exception):
                raise self.oneshot_reply
            return self.oneshot_reply

        patches = [mock.patch.object(type(get_provider("claude")), "oneshot", fake_oneshot),
                   mock.patch.object(web_steward, "_running_project_names", lambda: self.running),
                   mock.patch.object(web_steward, "_CARD_BACKGROUND", False)]
        self.running = set()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return cwd

    def test_refresh_card_writes_summary_and_logs(self):
        self._card_env()
        res = web_steward.refresh_card("kitap", steward_cfg(), reason="test")
        self.assertTrue(res["ok"], res)
        card = sw.load_card("kitap")
        self.assertEqual((card["summarized"], card["next_step"], card["goal"], card["phase_guess"]),
                         (True, "3. bölümü bitir", "Bir kitap yaz", "planned"))
        self.assertEqual(card["source_hash"], sw.build_raw_card(self.fleet["kitap"]["cwd"])["source_hash"])
        prompt, model, cwd_ = self.oneshot_calls[0]
        self.assertIn("Kitap", prompt)
        self.assertTrue(cwd_.endswith(os.path.join("steward", "oneshot")))     # nötr cwd, proje klasörü değil
        self.assertTrue(any(e["event"] == "card" and e["ok"] for e in sw.tail_log()))

    def test_refresh_card_failure_keeps_old_card_or_writes_raw(self):
        self._card_env()
        self.oneshot_reply = "özet yok, sadece düzyazı"
        res = web_steward.refresh_card("kitap", steward_cfg())
        self.assertFalse(res["ok"])
        raw_card = sw.load_card("kitap")                       # kart yoktu: ham kart yazıldı
        self.assertFalse(raw_card["summarized"])
        self.assertIn("ayrıştırılamadı", raw_card["last_error"])
        self.assertEqual(raw_card["goal"], "Kitap yaz")
        self.oneshot_reply = GOOD_JSON
        web_steward.refresh_card("kitap", steward_cfg())
        good = sw.load_card("kitap")
        self.assertTrue(good["summarized"])
        self.oneshot_reply = OneshotError("claude: 120s içinde yanıt vermedi")
        sw.upsert_project("kitap", goal="değişti")
        with open(os.path.join(self.fleet["kitap"]["cwd"], "TODO.md"), "a") as f:
            f.write("\n- yeni\n")
        res = web_steward.refresh_card("kitap", steward_cfg())
        after = sw.load_card("kitap")
        self.assertFalse(res["ok"])
        self.assertEqual((after["next_step"], after["summarized"]), ("3. bölümü bitir", True))   # eski kart bozulmadı
        self.assertEqual(after["attempt_hash"], sw.build_raw_card(self.fleet["kitap"]["cwd"])["source_hash"])

    def test_refresh_due_cards_rules(self):
        cwd = self._card_env()
        cfg = steward_cfg()
        for n in ("durdu", "calisan", "bitti"):
            d = _make_repo(os.path.join(self.dir.name, n), **{"TODO.md": n})
            self.fleet[n] = {"cwd": d, "model": "", "cli": "claude", "state": "active"}
            sw.upsert_project(n, phase="done" if n == "bitti" else "planned", priority=1 if n == "durdu" else 3)
        self.running = {"calisan"}
        got = web_steward.refresh_due_cards(cfg, limit=1)
        self.assertEqual([r["name"] for r in got], ["durdu"])           # öncelik 1, çalışan/done atlanır
        got = web_steward.refresh_due_cards(cfg, limit=10)
        self.assertEqual(sorted(r["name"] for r in got), ["kitap"])      # durdu'nun kartı artık taze; calisan çalışıyor
        self.assertEqual(web_steward.refresh_due_cards(cfg, limit=10), [])
        self.assertEqual(web_steward.refresh_due_cards(cfg, limit=0), [])
        with open(os.path.join(cwd, "TODO.md"), "a") as f:               # kaynak değişti -> yeniden
            f.write("\n- değişti\n")
        self.assertEqual([r["name"] for r in web_steward.refresh_due_cards(cfg, limit=10)], ["kitap"])
        sw.mark_card_stale("durdu")                                       # respawn sonrası bayat -> yeniden
        self.assertEqual([r["name"] for r in web_steward.refresh_due_cards(cfg, limit=10)], ["durdu"])
        self.running = {"calisan", "durdu"}                               # çalışırken yenilenmez
        sw.mark_card_stale("durdu")
        self.assertEqual(web_steward.refresh_due_cards(cfg, limit=10), [])

    def test_tick_runs_card_step_unless_disabled(self):
        self._card_env()
        sw.upsert_project("kitap", cadence_minutes=0)       # tick bu projeyi açmaya çalışmasın (yalnız kart adımı)
        settings.save_settings({"steward": {"enabled": "on"}})
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: []):
            res = web_steward.tick_once("test")
        self.assertTrue(res["ok"])
        self.assertIsNotNone(sw.load_card("kitap"))
        sw.save_card("kitap", {"source_hash": "x", "updated_at": 1.0, "stale": True})
        settings.save_settings({"steward": {"card_refresh": "off"}})
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: []):
            web_steward.tick_once("test")
        self.assertTrue(sw.load_card("kitap")["stale"])                    # kapalıyken dokunmaz
        settings.save_settings({"steward": {"card_refresh": "on", "cards_per_tick": "0"}})
        self.assertFalse(web_steward.card_tick(settings.steward_config()))

    def test_respawn_marks_card_stale(self):
        self._card_env()
        sw.save_card("kitap", {"source_hash": "x", "updated_at": 1.0})
        web_steward.configure(status_payload=lambda: {"sessions": []}, fleet_status=lambda: self.fleet,
                              start=lambda *a, **k: {"ok": True}, stop=lambda *a, **k: {"ok": True},
                              handover=lambda *a, **k: {"ok": True}, register_project=lambda *a, **k: {"ok": True})
        with mock.patch.object(web_steward, "_running", lambda name: None), \
                mock.patch.object(web_steward, "_ensure_running", lambda name, **kw: {"ok": True}), \
                mock.patch.object(web_steward, "_give_directive", lambda *a, **k: {"ok": True}):
            res = web_steward._apply(sw.Action("respawn", "kitap", "t"), steward_cfg(), sw.load_projects())
        self.assertTrue(res["ok"])
        self.assertTrue(sw.load_card("kitap")["stale"])

    def test_cards_in_context_projects_and_api(self):
        self._card_env()
        ctx = web_steward.http_get("/api/steward/context", {"name": ["kitap"]})
        self.assertIn("GOAL.md", ctx["docs"])                              # kart yokken ham belge başları
        self.assertNotIn("card", ctx)
        web_steward.refresh_card("kitap", steward_cfg())
        ctx = web_steward.http_get("/api/steward/context", {"name": ["kitap"]})
        self.assertEqual(ctx["card"]["next_step"], "3. bölümü bitir")
        self.assertNotIn("docs", ctx)                                      # kart varsa ham belge başı gitmez
        self.assertIn("GOAL.md", web_steward.http_get("/api/steward/context", {"name": ["kitap"], "docs": ["1"]})["docs"])
        self.assertEqual(web_steward.http_get("/api/steward/projects", {})["projects"][0]["next_step"], "3. bölümü bitir")
        self.assertEqual(web_steward.http_get("/api/steward/state", {})["projects"][0]["next_step"], "3. bölümü bitir")
        self.assertEqual(web_steward.http_get("/api/steward/cards", {})["cards"][0]["name"], "kitap")
        self.assertEqual(web_steward.http_get("/api/steward/card", {"name": ["kitap"]})["card"]["goal"], "Bir kitap yaz")
        self.assertFalse(web_steward.http_get("/api/steward/card", {"name": ["yok"]})["ok"])
        enriched = web_steward._enrich_item({"kind": "idle", "name": "kitap"}, sw.load_projects())
        self.assertEqual(enriched["card"]["next_step"], "3. bölümü bitir")
        self.assertNotIn("docs", enriched)
        r = web_steward.http_post("/api/steward/cards/refresh", {"name": "kitap"})
        self.assertEqual(r, {"ok": True, "queued": "kitap"})
        self.assertFalse(web_steward.http_post("/api/steward/cards/refresh", {"name": "olmayan"})["ok"])
        self.assertTrue(web_steward.http_post("/api/steward/cards/refresh", {})["ok"])
        self.assertTrue(web_steward._CARD_LOCK.acquire(blocking=False))     # iş sürerken ikincisi reddedilir
        try:
            self.assertFalse(web_steward.http_post("/api/steward/cards/refresh", {})["ok"])
        finally:
            web_steward._CARD_LOCK.release()


    # ── observe kipi + günlük özet (motor) ──────────────────────────────────

    def _observe_env(self, mode):
        settings.save_settings({"steward": {"enabled": "on", "mode": mode, "card_refresh": "off"}})
        self.touched = []
        patches = [mock.patch.object(web_steward, "_ensure_running",
                                     lambda name, **kw: self.touched.append(("ensure", name)) or {"ok": False, "error": "no tmux"}),
                   mock.patch.object(web_steward, "_running", lambda name: None),
                   # günlük özet saati gerçek saate bağlı (21'den sonra bugünün tick'lerini katlardı); kendi testi var
                   mock.patch.object(web_steward, "maybe_daily_summary", lambda cfg, now: None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_observe_tick_records_would_and_touches_nothing(self):
        self._observe_env("observe")
        sw.upsert_project("a", phase="planned", cadence_minutes=60, priority=1)
        sw.upsert_project("b", phase="planned", cadence_minutes=60, priority=2)
        views = [_view("a", running=False), _view("b", running=False)]
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: views):
            r1 = web_steward.tick_once("timer")
            r2 = web_steward.tick_once("timer")
            r3 = web_steward.tick_once("timer")
        self.assertEqual(self.touched, [])                                    # hiçbir oturuma dokunulmadı
        self.assertEqual((r1["actions"], r1["mode"]), ([], "observe"))
        self.assertEqual([(d["kind"], d["name"]) for d in r1["dry"]], [("start", "a")])
        self.assertEqual([(d["kind"], d["name"]) for d in r2["dry"]], [("start", "b")])   # a'ya sonsuz tekrar yok
        self.assertEqual(r3["dry"], [])
        self.assertTrue(web_steward._RECENT[0]["dry"])
        log = sw.tail_log(50)
        self.assertEqual([e["name"] for e in log if e["event"] == "would:start"], ["a", "b"])
        self.assertEqual([e["trigger"] for e in log if e["event"] == "tick"], ["timer"] * 3)
        self.assertFalse(any(e["event"] == "action" for e in log))
        self.assertEqual(sw.load_projects()["a"].last_visit, 0.0)             # gerçek uğrama kaydı da yok
        self.assertEqual(web_steward.summary()["mode"], "observe")

    def test_observe_still_runs_questions_ideas_and_phase_changes(self):
        self._observe_env("observe")
        sw.upsert_project("a", phase="planning", cadence_minutes=0)
        done = _view("a", last_assistant="STEWARD-ASK: A mı B mi?\nSTEWARD-IDEA: yeni bir şey\nSTEWARD-PLAN-READY")
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: [done]):
            r = web_steward.tick_once("timer")
        self.assertEqual(sorted(a["kind"] for a in r["actions"]), ["ask_user", "idea", "set_phase"])
        self.assertTrue(all(a["ok"] for a in r["actions"]))
        self.assertEqual(sw.load_projects()["a"].phase, "planned")
        self.assertEqual(len(sw.open_questions()), 1)
        self.assertEqual(len(sw.load_ideas()), 1)
        # STEWARD-DONE: faz değişir ama oturum DURDURULMAZ (stop observe'da would:)
        done2 = _view("a", last_assistant="bitti\nSTEWARD-DONE")
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: [done2]):
            r = web_steward.tick_once("timer")
        self.assertEqual([a["kind"] for a in r["actions"]], ["set_phase"])
        self.assertEqual([(d["kind"], d["name"]) for d in r["dry"]], [("stop", "a")])

    def test_act_mode_applies_and_logs_actions(self):
        self._observe_env("act")
        sw.upsert_project("a", phase="planned", cadence_minutes=60)
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: [_view("a", running=False)]):
            r = web_steward.tick_once("timer")
        self.assertEqual(self.touched, [("ensure", "a")])
        self.assertEqual(([a["kind"] for a in r["actions"]], r["dry"]), (["start"], []))
        self.assertFalse(any(e["event"].startswith("would:") for e in sw.tail_log(50)))

    def test_brain_calls_are_dry_in_observe_but_cli_calls_apply(self):
        calls = []
        with mock.patch.object(web_steward, "_give_directive", lambda p, text, **kw: calls.append(("dir", p.name, text)) or {"ok": True}):
            settings.save_settings({"steward": {"mode": "observe"}})
            sw.upsert_project("a", phase="planned")
            r = web_steward.http_post("/api/steward/directive", {"name": "a", "text": "yap", "actor": "brain", "reason": "boş"})
            self.assertEqual((r["ok"], r["dry"], calls), (True, True, []))
            r = web_steward.http_post("/api/steward/stop", {"name": "a", "actor": "brain", "reason": "x"})
            self.assertTrue(r["dry"])
            r = web_steward.http_post("/api/steward/handover", {"name": "a", "actor": "brain"})
            self.assertTrue(r["dry"])
            r = web_steward.http_post("/api/steward/restart", {"name": "a", "text": "yeni", "actor": "brain", "reason": "r"})
            self.assertTrue(r["dry"])
            self.assertEqual(self.calls, [])                                       # stop/handover callback'i çağrılmadı
            self.assertEqual(sorted(e["event"] for e in sw.tail_log(50) if e["event"].startswith("would:")),
                             ["would:directive", "would:handover", "would:restart", "would:stop"])
            # insanın CLI'ı (actor yok) observe'da da uygulanır
            r = web_steward.http_post("/api/steward/directive", {"name": "a", "text": "yap"})
            self.assertEqual((r["ok"], calls), (True, [("dir", "a", "yap")]))
            # act kipinde beyin de uygular
            settings.save_settings({"steward": {"mode": "act"}})
            web_steward.http_post("/api/steward/directive", {"name": "a", "text": "yine", "actor": "brain"})
            self.assertEqual(calls[-1], ("dir", "a", "yine"))
            # MCP araçları actor=brain gönderir
            sent = []
            with mock.patch.object(mcp_queue, "_api", lambda port, m, path, body=None: sent.append(body) or {"ok": True}):
                mcp_steward._directive(1, {"name": "a", "text": "t"})
                mcp_steward._restart(1, {"name": "a", "directive": "d", "reason": "r"})
                mcp_steward._stop(1, {"name": "a", "reason": "r"})
                mcp_steward._handover(1, {"name": "a"})
            self.assertTrue(all(b.get("actor") == "brain" for b in sent) and len(sent) == 4)

    def test_brain_cannot_touch_unregistered_session(self):
        """P0 kapısı (`_target`): beyin kaynaklı stop/handover/restart/directive kullanıcının kayıtsız (ad hoc) oturumuna
        REDDEDİLİR (observe de act de); aynı çağrı insan kaynaklıysa (`actor` yok) eskisi gibi uygulanır."""
        dirs = []
        with mock.patch.object(web_steward, "_give_directive", lambda p, text, **kw: dirs.append((p.name, text)) or {"ok": True}), \
                mock.patch.object(web_steward, "_running", lambda name: types.SimpleNamespace(name=name)), \
                mock.patch.object(web_steward.inst_mod, "get_instance", lambda name: None):
            sw.upsert_project("a", phase="planned")
            for mode in ("act", "observe"):
                settings.save_settings({"steward": {"mode": mode}})
                for path, extra in (("stop", {}), ("handover", {}), ("restart", {"text": "x"}), ("directive", {"text": "x"})):
                    r = web_steward.http_post("/api/steward/" + path, dict(extra, name="adhocsess", actor="brain", reason="r"))
                    self.assertEqual((mode, path, r["ok"], "dry" in r), (mode, path, False, False))
            self.assertEqual((self.calls, dirs), ([], []))                         # hiçbir geri çağrı çalışmadı
            self.assertFalse(any(e["event"].startswith("would:") for e in sw.tail_log(50)))
            self.assertEqual(sum(1 for e in sw.tail_log(50) if e["event"] == "target_denied"), 8)
            # geçersiz ad da beyin için red (stop/handover adı bugüne dek doğrulamıyordu)
            self.assertFalse(web_steward.http_post("/api/steward/stop", {"name": "", "actor": "brain"})["ok"])
            self.assertFalse(web_steward.http_post("/api/steward/stop", {"name": "x; rm", "actor": "brain"})["ok"])
            self.assertEqual(self.calls, [])
            # insan kaynaklı çağrı kayıtsız oturuma eskisi gibi gider
            self.assertTrue(web_steward.http_post("/api/steward/stop", {"name": "adhocsess"})["ok"])
            self.assertTrue(web_steward.http_post("/api/steward/handover", {"name": "adhocsess"})["ok"])
            self.assertTrue(web_steward.http_post("/api/steward/directive", {"name": "adhocsess", "text": "x"})["ok"])
            self.assertEqual(self.calls, [("stop", "adhocsess"), ("handover", "adhocsess")])
            self.assertEqual(dirs, [("adhocsess", "x")])

    def test_brain_may_touch_brain_and_registered_projects(self):
        settings.save_settings({"steward": {"mode": "act"}})
        sw.upsert_project("a", phase="planned")
        brain = steward_cfg().brain_name
        with mock.patch.object(web_steward, "_running", lambda name: None):
            self.assertTrue(web_steward.http_post("/api/steward/stop", {"name": "a", "actor": "brain"})["ok"])
            self.assertTrue(web_steward.http_post("/api/steward/stop", {"name": brain, "actor": "brain"})["ok"])
            self.assertTrue(web_steward.http_post("/api/steward/handover", {"name": "a", "actor": "brain"})["ok"])
        self.assertEqual(self.calls, [("stop", "a"), ("stop", brain), ("handover", "a")])

    def test_apply_gate_denies_engine_actions_on_unregistered_sessions(self):
        """`_apply` motor eylemleri de aynı kapıdan geçer; deliver_answer (kayıtsız oturumun kaynağına cevap) etkilenmez."""
        cfg = steward_cfg()
        projects = {"a": sw.Project(name="a")}
        with mock.patch.object(web_steward.inst_mod, "get_instance", lambda name: None):
            for kind in ("stop", "handover", "respawn"):
                r = web_steward._apply(sw.Action(kind, "adhocsess", "t"), cfg, projects)
                self.assertFalse(r["ok"], kind)
            self.assertEqual(self.calls, [])
            self.assertTrue(web_steward._apply(sw.Action("stop", "a", "t"), cfg, projects)["ok"])
            self.assertTrue(web_steward._apply(sw.Action("handover", cfg.brain_name, "t"), cfg, projects)["ok"])
            self.assertEqual(self.calls, [("stop", "a"), ("handover", cfg.brain_name)])

    def test_daily_summary_runs_once_after_hour_and_notifies(self):
        settings.save_settings({"steward": {"enabled": "on", "summary_hour": "21", "card_refresh": "off"}})
        cfg = settings.steward_config()
        notes = []
        at = lambda h: time.mktime((2026, 10, 19, h, 5, 0, 0, 0, -1))   # noqa: E731
        sw.log_event("would:start", name="p1")
        with mock.patch.object(web_steward, "notify_phone", lambda text: notes.append(text) or True):
            self.assertIsNone(web_steward.maybe_daily_summary(cfg, at(20)))        # saat gelmedi
            self.assertEqual(notes, [])
            path = web_steward.maybe_daily_summary(cfg, at(21))
            self.assertIsNone(web_steward.maybe_daily_summary(cfg, at(22)))        # günde bir
        self.assertTrue(path.endswith(os.path.join("daily", "2026-10-19.md")))
        self.assertEqual(sw.load_state()["summary_date"], "2026-10-19")
        self.assertEqual(len(notes), 1)
        self.assertTrue(any(e["event"] == "summary" and e["notified"] for e in sw.tail_log(20)))
        # tick içinden: enabled iken tetiklenir, kapalıyken (elle tick) tetiklenmez
        sw.save_state({})
        settings.save_settings({"steward": {"enabled": "off"}})
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: []), \
                mock.patch.object(web_steward, "maybe_daily_summary", lambda cfg, now: notes.append("tick-summary")):
            web_steward.tick_once("manual")
            self.assertNotIn("tick-summary", notes)
            settings.save_settings({"steward": {"enabled": "on"}})
            web_steward.tick_once("timer")
        self.assertIn("tick-summary", notes)

    def test_summary_api_and_cli(self):
        import contextlib
        import io
        from claudeops.commands import steward as steward_cli
        sw.log_event("would:start", name="p1")
        today = time.strftime("%Y-%m-%d")
        r = web_steward.http_get("/api/steward/summary", {})
        self.assertTrue(r["ok"])
        self.assertEqual(r["date"], today)
        self.assertIn("start 1 (p1)", r["text"])
        self.assertFalse(r["saved"])
        self.assertIn("Steward daily summary", web_steward.http_get("/api/steward/summary", {"lang": ["en"]})["text"])
        self.assertFalse(web_steward.http_get("/api/steward/summary", {"date": ["dün"]})["ok"])
        ns = type("A", (), {"date": "", "lang": "", "save": True})()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(steward_cli.cmd_summary(ns), 0)
        self.assertIn("start 1 (p1)", buf.getvalue())
        self.assertTrue(os.path.isfile(sw.daily_path(today)))
        self.assertTrue(web_steward.http_get("/api/steward/summary", {})["saved"])
        bad = type("A", (), {"date": "x", "lang": "", "save": False})()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(steward_cli.cmd_summary(bad), 1)


    def test_handover_route_marks_pending(self):
        self.assertTrue(web_steward.http_post("/api/steward/handover", {"name": "a"})["ok"])
        self.assertIn("a", sw.load_state()["ho_pending"])
        self.assertEqual(self.calls, [("handover", "a")])


if __name__ == "__main__":
    unittest.main()


class QuestionPageHttpTest(_Tmp):
    """Gerçek HTTP (`web._Handler`): `/q/<id>` panel token'ı olmadan da sorunun anahtarıyla açılır, form POST cevaplar."""

    def setUp(self):
        super().setUp()
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from claudeops.commands import web
        self.urllib = urllib
        p = mock.patch.object(web._Handler, "token", "tok")
        p.start()
        self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def req(self, path, data=None, headers=None):
        req = self.urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                          method="POST" if data is not None else "GET", headers=headers or {})
        try:
            with self.urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode("utf-8"), r.headers
        except self.urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8"), e.headers

    def test_question_page_round_trip(self):
        q = sw.add_question("p", "Yayınlayalım mı?", options=["evet", "hayır"])
        status, body, _ = self.req(f"/q/{q.id}")
        self.assertEqual(status, 401)
        self.assertIn("Bağlantı geçersiz", body)                                    # HTML, panelin 401'i değil
        status, body, headers = self.req(f"/q/{q.id}?k={q.key}")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("value='evet'", body)
        self.assertEqual(self.req(f"/q/{q.id}?token=tok")[0], 200)                 # panel token'ı da geçer
        self.assertEqual(self.req("/q/yok?k=x")[0], 404)
        form = b"answer=hay%C4%B1r"
        with mock.patch.object(web_steward.web_ws, "notify_status_changed", lambda: None):
            status, body, _ = self.req(f"/q/{q.id}?k={q.key}", data=form,
                                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 200)
        self.assertIn("Cevap kaydedildi", body)
        self.assertEqual(sw.find_question(q.id).answer, "hayır")
        big = b"answer=" + b"x" * (web_steward.MAX_FORM_BYTES + 1)
        self.assertEqual(self.req(f"/q/{q.id}?k={q.key}", data=big)[0], 400)
        self.assertEqual(self.req("/api/steward/state")[0], 401)                     # geri kalan yüzey token ister

    def test_notify_phone_sets_click_header(self):
        import threading
        seen = {}
        done = threading.Event()
        with open(web_steward.NTFY_TOPIC_FILE, "w", encoding="utf-8") as f:
            f.write("topic1\n")

        class _Resp:
            def read(self):
                return b""

        def fake_open(req, timeout=0):
            seen.update(url=req.full_url, headers=dict(req.headers), data=req.data)
            done.set()
            return _Resp()

        with mock.patch.object(web_steward.urllib.request, "urlopen", fake_open):
            self.assertTrue(web_steward.notify_phone("soru?", click="https://t/q/1?k=a"))
            self.assertTrue(done.wait(5))
        self.assertEqual(seen["url"], "https://ntfy.sh/topic1")
        self.assertEqual((seen["headers"].get("Click"), seen["headers"].get("Title")), ("https://t/q/1?k=a", "claudeops degnekci"))
        self.assertEqual(seen["data"], "soru?".encode("utf-8"))



class BrainAuthorityAndDeferTest(unittest.TestCase):
    """Beyin sahip kararına cevap veremez; meşgul/yeni direktif almış oturuma direktif ertelenir."""

    def test_non_routine_question_is_owner_only(self):
        q = sw.Question(id="q1", project="cli", text="Devam edeyim mi?", created_at=0.0, routine=False)
        ok, why = sw.brain_may_answer(q)
        self.assertFalse(ok)
        self.assertIn("owner", why)

    def test_routine_with_commit_push_is_owner_only(self):
        for t in ("E4/E5 için commit + push yapayım mı?", "install-ucli.sh çalıştırayım mı?", "dosyayı sileyim mi? delete"):
            q = sw.Question(id="q2", project="cli", text=t, created_at=0.0, routine=True)
            self.assertFalse(sw.brain_may_answer(q)[0], t)

    def test_plain_routine_is_answerable(self):
        q = sw.Question(id="q3", project="cli", text="Hangi modelle, sırayla mı ayrı ajanla mı?", created_at=0.0, routine=True)
        self.assertEqual(sw.brain_may_answer(q), (True, ""))

    def test_defer_reason(self):
        self.assertEqual(sw.directive_defer_reason(True, 0.0, 1000.0), "busy")
        self.assertEqual(sw.directive_defer_reason(False, 960.0, 1000.0), "recent")      # 40 sn önce direktif gitti
        self.assertEqual(sw.directive_defer_reason(False, 800.0, 1000.0), "")
        self.assertEqual(sw.directive_defer_reason(None, 0.0, 1000.0), "")               # bilinmiyor = engelleme

    def test_tour_retry_gap_after_deferral(self):
        self.assertEqual(sw.Config().tour_retry_minutes, 5)


class TourDeliveryTest(unittest.TestCase):
    def test_short_tour_inline(self):
        with tempfile.TemporaryDirectory() as d:
            msg, path = sw.tour_delivery("kısa", d, 1000.0)
            self.assertEqual((msg, path), ("kısa", ""))
            self.assertFalse(os.path.exists(os.path.join(d, "tours")))

    def test_long_tour_goes_to_file_and_old_files_pruned(self):
        with tempfile.TemporaryDirectory() as d:
            long = "x" * (sw.TOUR_INLINE_MAX_CHARS + 1)
            paths = []
            for i in range(8):
                msg, p = sw.tour_delivery(long, d, 1000.0 + i)
                paths.append(p)
                self.assertIn(p, msg)
                self.assertLess(len(msg), 400)
                self.assertEqual(Path(p).read_text(encoding="utf-8"), long)
            left = sorted(os.listdir(os.path.join(d, "tours")))
            self.assertEqual(len(left), sw.TOUR_FILES_KEEP)
            self.assertTrue(os.path.exists(paths[-1]))
            self.assertFalse(os.path.exists(paths[0]))


class ShutdownKeepModeTest(unittest.TestCase):
    """Oturum başına "keep": devir alınır, oturum durdurulmaz (stage kept); "stop"/modes yoksa eski davranış."""

    def _ready(self, modes):
        v = _view("ncs", last_activity=100.0)
        projects = {"ncs": sw.Project(name="ncs")}
        _a, sd, _d = sw.plan_shutdown([v], projects, {"modes": modes} if modes else {}, _cfg(), 1000.0)
        v2 = _view("ncs", last_activity=1500.0, last_assistant=sw.READY_FOR_HANDOVER)
        return sw.plan_shutdown([v2], projects, sd, _cfg(), 1600.0)

    def test_keep_does_not_stop(self):
        acts, sd, _d = self._ready({"ncs": "keep"})
        self.assertEqual(acts, [])
        self.assertEqual(sd["items"]["ncs"]["stage"], "kept")

    def test_default_stops(self):
        acts, sd, _d = self._ready(None)
        self.assertEqual([(a.kind, a.name) for a in acts], [("stop", "ncs")])
        self.assertEqual(sd["items"]["ncs"]["stage"], "closed")


class ShutdownBlockersTest(unittest.TestCase):
    """Sessizlik tek başına "iş bitti" değildir: açık varaka işi bekleyen oturum devir almaz."""

    def _run(self, blockers):
        v = _view("ncs", last_activity=100.0)
        projects = {"ncs": sw.Project(name="ncs")}
        return sw.plan_shutdown([v], projects, {}, _cfg(), 1000.0, blockers=blockers)

    def test_quiet_session_without_blocker_gets_handover(self):
        acts, sd, done = self._run({})
        self.assertEqual([(a.kind, a.name) for a in acts], [("handover", "ncs")])

    def test_blocked_session_waits_and_records_reason(self):
        acts, sd, done = self._run({"ncs": "open varaka job (1)"})
        self.assertEqual(acts, [])
        self.assertEqual(sd["items"]["ncs"]["stage"], "wait")
        self.assertEqual(sd["items"]["ncs"]["blocked"], "open varaka job (1)")
        self.assertFalse(done)

    def test_blocked_session_left_open_after_wait_max(self):
        _a, sd, _d = self._run({"ncs": "open varaka job (1)"})
        v = _view("ncs", last_activity=100.0)
        acts, sd, done = sw.plan_shutdown([v], {"ncs": sw.Project(name="ncs")}, sd, _cfg(),
                                          1000.0 + sw.SHUTDOWN_WAIT_MAX_SECONDS + 1, blockers={"ncs": "open varaka job (1)"})
        self.assertEqual(acts, [])
        self.assertEqual(sd["items"]["ncs"]["stage"], "busy_left")

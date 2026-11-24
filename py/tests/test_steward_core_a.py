"""Değnekçi testleri (test_steward.py bölünmüş parça: b). Çalıştırma: python3 -m pytest py/tests/test_steward_core_a.py"""
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

    def test_defer_answer_keeps_question_open(self):
        q = sw.add_question("p", "A mı B mi?", source="s")
        r = sw.answer_question(q.id, "Sonra")
        self.assertEqual((r.status, r.answer), ("open", ""))
        self.assertGreater(r.deferred_until, 0)
        self.assertEqual(len(sw.open_questions()), 1)
        r = sw.answer_question(q.id, "A")      # gerçek cevap ertelemeyi kapatır
        self.assertEqual((r.status, r.answer, r.deferred_until), ("answered", "A", 0.0))

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
        j = sw.update_idea(i.id, status="dropped", reason="  proje içi\nküçük iş  ")
        self.assertEqual((j.status, j.reason), ("dropped", "proje içi küçük iş"))
        self.assertEqual(sw.load_ideas()[0].reason, "proje içi küçük iş")      # kalıcı
        self.assertEqual(sw.update_idea(i.id, status="later").reason, "proje içi küçük iş")   # reason verilmezse korunur
        sw.log_event("x", a=1)
        self.assertEqual(sw.tail_log(5)[-1]["a"], 1)

    def test_persona_override_and_bundled(self):
        self.assertIn("değnekçi", sw.persona_text("").lower())
        self.assertEqual(sw.persona_text("  özel  "), "özel\n")


class MarkerTest(unittest.TestCase):
    def test_scan_markers_ask_ending_with_colon_takes_following_lines(self):
        # prompti 13 Kas: "Seçenekler:" sonrası alt satırlar kayboluyor, soru seçeneksiz kalıyordu
        txt = ("STEWARD-ASK: Makalenin yönü ne olsun? Seçenekler:\n"
               "- (a) survey\n- (b) yöntem, öneri: (b)\n\nSonraki paragraf soru değil.\n"
               "STEWARD-NEXT: survey")
        m = sw.scan_markers(txt)
        self.assertEqual(m["asks"], ["Makalenin yönü ne olsun? Seçenekler: (a) survey (b) yöntem, öneri: (b)"])
        self.assertEqual(m["next"], "survey")
        # ':' ile bitmeyen tek satırlık soru alt satırı yutmaz
        m2 = sw.scan_markers("STEWARD-ASK: tamam mı?\nbaşka düzyazı")
        self.assertEqual(m2["asks"], ["tamam mı?"])

    def test_scan_markers_ignores_writing_examples(self):
        txt = ("Protokol:\n- takıldın: `STEWARD-BLOCKED: <nerede takıldın>`\n> STEWARD-ASK: alıntı soru?\n"
               "```\nSTEWARD-ASK: kod bloğundaki soru?\nSTEWARD-IDEA: kod fikri\n```\n"
               "Takıldım: STEWARD-BLOCKED: <kullanıcı aksiyonu>`...\n")
        m = sw.scan_markers(txt)
        self.assertEqual((m["asks"], m["blocked"], m["ideas"]), ([], [], []))
        m = sw.scan_markers("```\nx\n```\nSTEWARD-ASK: gerçek soru mu?\n- `STEWARD-IDEA: gerçek fikir`\n")
        self.assertEqual((m["asks"], m["ideas"]), (["gerçek soru mu?"], ["gerçek fikir"]))

    def test_scan_markers_ignores_inline_code_mention_in_prose(self):
        # 2026-10-25: açıklama cümlesi fikir kutusuna "` satırı yazmasına bağlı" diye yarım kayıt düşürmüştü
        txt = ("Fikir kaydı `STEWARD-IDEA: <fikir>` satırı yazmasına bağlı.\n"
               "Bir de `STEWARD-ASK: <soru>` yaz, motor tarar.\n")
        m = sw.scan_markers(txt)
        self.assertEqual((m["asks"], m["ideas"]), ([], []))
        m = sw.scan_markers("- `STEWARD-IDEA: gerçek fikir`\nSTEWARD-ASK: gerçek `kod` sorusu mu?\n")
        self.assertEqual((m["asks"], m["ideas"]), (["gerçek `kod` sorusu mu?"], ["gerçek fikir"]))

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
        v.busy, v.last_assistant = False, "...\n## READY FOR HANDOVER özet"
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
        acts, _ = sw.plan_tick([_view("a", last_assistant="STEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt")], self.projects, {}, _cfg(), self.now, [], [])
        self.assertEqual(sorted(a.kind for a in acts if a.name == "a"), ["set_phase", "stop"])

    def test_done_confirmed_with_open_owner_question_pauses_not_done(self):
        """D4: sahibe açık soru varken STEWARD-DONE-CONFIRMED faz `done` yapmaz, `paused` yapar (telefona gitmemiş soru gerekçede görünür)."""
        q = sw.Question(id="q1", project="a", text="hangisi?", created_at=self.now - 60)     # notified_at=0
        acts, _ = sw.plan_tick([_view("a", last_assistant="STEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt")], self.projects, {}, _cfg(), self.now, [q], [])
        ph = [a for a in acts if a.kind == "set_phase" and a.name == "a"]
        self.assertEqual([a.payload["phase"] for a in ph], ["paused"])
        self.assertIn("telefona gitmedi", ph[0].reason if hasattr(ph[0], "reason") else str(ph[0]))
        q.status = "answered"
        acts, _ = sw.plan_tick([_view("a", last_assistant="STEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt")], self.projects, {}, _cfg(), self.now, [q], [])
        self.assertEqual([a.payload["phase"] for a in acts if a.kind == "set_phase" and a.name == "a"], ["done"])

    def test_done_marker_ignored_when_project_notes_have_no_done_tag(self):
        self.projects["a"].notes = "sürekli geliştirme " + sw.NO_DONE_TAG
        acts, _ = sw.plan_tick([_view("a", last_assistant="STEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt")], self.projects, {}, _cfg(), self.now, [], [])
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

    def test_todo_change_opens_active_project_without_waiting_cadence(self):
        cfg = _cfg(max_active=4, max_starts_per_tick=5)
        self.projects["a"].last_visit = self.projects["b"].last_visit = self.now - 10 * 60   # cadence dolmamış
        sha = {"v": "h1"}
        kw = dict(open_work=lambda n: 2, todo_sha=lambda n: sha["v"])
        acts, st = sw.plan_tick([], self.projects, {}, cfg, self.now, [], [], **kw)
        self.assertEqual([a for a in acts if a.kind == "start"], [])       # ilk gözlem tetiklemez
        acts, st = sw.plan_tick([], self.projects, st, cfg, self.now, [], [], **kw)
        self.assertEqual([a for a in acts if a.kind == "start"], [])       # değişmedi
        sha["v"] = "h2"
        acts, st = sw.plan_tick([], self.projects, st, cfg, self.now, [], [], **kw)
        self.assertEqual(sorted(a.name for a in acts if a.kind == "start"), ["a", "b"])
        # açık iş 0 ise değişim açmaz
        sha["v"] = "h3"
        self.projects["a"].last_visit = self.projects["b"].last_visit = self.now - 10 * 60
        acts, _ = sw.plan_tick([], self.projects, st, cfg, self.now, [], [], open_work=lambda n: 0, todo_sha=lambda n: sha["v"])
        self.assertEqual([a for a in acts if a.kind == "start"], [])

    def test_todo_change_reopens_done_project_to_planned(self):
        """17 Kas (marwan): reviewer bulgusu done projenin TODO'suna düşünce planned'a çekilir (paused'a dokunulmaz, yalnız soru)."""
        cfg = _cfg(max_active=4, max_starts_per_tick=5)
        self.projects["c"].phase = "done"
        sha = {"v": "h1"}
        kw = dict(open_work=lambda n: 21, todo_sha=lambda n: sha["v"])
        _, st = sw.plan_tick([], self.projects, {}, cfg, self.now, [], [], **kw)
        sha["v"] = "h2"
        acts, _ = sw.plan_tick([], self.projects, st, cfg, self.now, [], [], **kw)
        self.assertEqual([(a.name, a.payload) for a in acts if a.kind == "set_phase"], [("c", {"phase": "planned"})])

    def test_todo_change_paused_project_asks_owner_once_per_day(self):
        cfg = _cfg(max_active=4, max_starts_per_tick=5)
        sha = {"v": "h1"}
        kw = dict(open_work=lambda n: 3, todo_sha=lambda n: sha["v"])
        acts, st = sw.plan_tick([], self.projects, {}, cfg, self.now, [], [], **kw)
        asks = [a for a in acts if a.kind == "ask_user" and a.name == "c"]
        self.assertEqual(len(asks), 1)          # ilk gözlem de sorar (21 Kas: dolu TODO ile sonsuza dek tetiksiz kalmasın)
        self.assertFalse([a for a in acts if a.kind == "start" and a.name == "c"])   # paused AÇILMAZ
        sha["v"] = "h2"
        acts, st = sw.plan_tick([], self.projects, st, cfg, self.now, [], [], **kw)
        self.assertFalse([a for a in acts if a.kind == "ask_user" and a.name == "c"])   # günde 1
        sha["v"] = "h3"
        acts, _ = sw.plan_tick([], self.projects, st, cfg, self.now + 3600, [], [], **kw)
        self.assertFalse([a for a in acts if a.kind == "ask_user" and a.name == "c"])   # günde 1

    def test_first_observation_done_project_with_open_work_goes_planned(self):
        cfg = _cfg(max_active=4, max_starts_per_tick=5)
        self.projects["c"].phase = "done"
        kw = dict(open_work=lambda n: 68, todo_sha=lambda n: "h1")
        acts, st = sw.plan_tick([], self.projects, {}, cfg, self.now, [], [], **kw)
        self.assertEqual([(a.name, a.payload) for a in acts if a.kind == "set_phase"], [("c", {"phase": "planned"})])
        acts, _ = sw.plan_tick([], self.projects, st, cfg, self.now, [], [], **kw)    # aynı sha: tekrar tetiklenmez
        self.assertFalse([a for a in acts if a.kind == "set_phase"])

    def test_daily_sweep_done_project_with_unchanged_sha(self):
        cfg = _cfg(max_active=4, max_starts_per_tick=5)
        self.projects["c"].phase = "done"
        kw = dict(open_work=lambda n: 68, todo_sha=lambda n: "h1")
        st = {"todo_seen": {"c": "h1"}}            # baz kayıtlı, sha değişmiyor (au örneği)
        acts, st = sw.plan_tick([], self.projects, st, cfg, self.now, [], [], **kw)
        self.assertEqual([a.name for a in acts if a.kind == "set_phase"], ["c"])
        acts, st = sw.plan_tick([], self.projects, st, cfg, self.now + 3600, [], [], **kw)
        self.assertFalse([a for a in acts if a.kind == "set_phase"])           # günde 1
        acts, _ = sw.plan_tick([], self.projects, st, cfg, self.now + 25 * 3600, [], [], **kw)
        self.assertEqual([a.name for a in acts if a.kind == "set_phase"], ["c"])

    def test_daily_sweep_paused_asks_once(self):
        cfg = _cfg(max_active=4, max_starts_per_tick=5)
        kw = dict(open_work=lambda n: 3, todo_sha=lambda n: "h1")
        acts, st = sw.plan_tick([], self.projects, {"todo_seen": {"c": "h1"}}, cfg, self.now, [], [], **kw)
        self.assertEqual(len([a for a in acts if a.kind == "ask_user" and a.name == "c"]), 1)
        acts, _ = sw.plan_tick([], self.projects, st, cfg, self.now + 3600, [], [], **kw)
        self.assertFalse([a for a in acts if a.kind == "ask_user" and a.name == "c"])

    def test_only_fable_cila_open_work_does_not_trigger(self):
        cfg = _cfg(max_active=4, max_starts_per_tick=5)
        self.projects["c"].phase = "done"
        kw = dict(open_work=lambda n: 3, open_work_real=lambda n: 0, todo_sha=lambda n: "h1")
        acts, _ = sw.plan_tick([], self.projects, {}, cfg, self.now, [], [], **kw)
        self.assertFalse([a for a in acts if a.kind in ("set_phase", "ask_user") and a.name == "c"])

    def test_drain_starts_nothing_but_keeps_answers_and_running(self):
        cfg = _cfg(max_active=4, max_starts_per_tick=5, drain=True)
        acts, _ = sw.plan_tick([], self.projects, {}, cfg, self.now, [], [])
        self.assertEqual([a for a in acts if a.kind == "start"], [])
        acts, _ = sw.plan_tick([_view("b", last_assistant="STEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt")], self.projects, {}, cfg, self.now, [], [])
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
        self.assertEqual([a.kind for a in acts if a.name == "zk_x20261020" and a.kind != "close_stale_answer"], [])   # kapalıysa açılmaz

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


class ScanCacheTest(_Tmp):
    """TODO 2026-10-28 (21): `find_sessions` N+1: tick içinde tek tarama, oturum değiştiren eylemden sonra yenilenir."""

    def test_scan_is_cached_inside_a_scope_and_invalidated_by_start(self):
        calls = []

        def fake(measure_cpu=False):
            calls.append(1)
            return []
        web_steward.configure(start=lambda *a, **k: {"ok": True}, stop=lambda *a, **k: {"ok": True})
        with mock.patch.object(web_steward, "find_sessions", fake):
            web_steward._scan()
            web_steward._scan()
            self.assertEqual(len(calls), 2)                    # kapsam DIŞI: her çağrı taze (eski davranış)
            calls.clear()
            with web_steward._scan_scope():
                for _ in range(5):
                    web_steward._scan()
                self.assertEqual(len(calls), 1)               # kapsam içi: tek tarama
                web_steward._act("start", "x")                # oturum kümesi değişti
                web_steward._scan()
                web_steward._scan()
                self.assertEqual(len(calls), 2)               # yalnız bir yeni tarama
            web_steward._scan()
            self.assertEqual(len(calls), 3)                   # kapsam kapandı: taze


class EngineSmallsTest(_Tmp):
    """TODO 2026-10-28 (21) motor küçükleri."""

    def test_fail_logged_is_pruned_and_thread_safe(self):
        web_steward._FAIL_LOGGED.clear()
        ctx = web_steward._ctx()
        old = time.time() - web_steward.FAIL_LOG_REPEAT_SECONDS - 5
        web_steward._FAIL_LOGGED[("x", "start", "a", "eski neden")] = old
        web_steward._remember(sw.Action("start", "b", "r"), {"ok": False, "error": "yeni neden"}, ctx)
        self.assertNotIn(("x", "start", "a", "eski neden"), web_steward._FAIL_LOGGED)      # süresi dolan anahtar budandı
        self.assertTrue(any(k[3] == "yeni neden" for k in web_steward._FAIL_LOGGED))
        web_steward._FAIL_LOGGED.clear()

    def test_shutdown_blockers_survive_corrupt_jobs_file(self):
        v = sw.SessionView(name="ncs", running=True, cwd="/x", cli="claude")
        with mock.patch.object(web_steward.sj, "load_jobs", side_effect=ValueError("bozuk")), \
                mock.patch.object(web_steward, "find_sessions", lambda measure_cpu=False: []), \
                mock.patch.object(web_steward, "_project_for_session", lambda *a, **k: None):
            out = web_steward._shutdown_blockers([v], {}, web_steward._world(), sw.paths_for("default"))
        self.assertEqual(out, {})          # çökmez; bg-shell denetimine kadar ilerler


class ShutdownOnlyLeavesPausedTest(_Tmp):
    """Sahip kararı 2026-10-29: kısmi kapatma fazı geri yüklemez; bitince `left_paused` olay + durumda uyarı."""

    def test_done_records_left_paused_and_warns(self):
        with mock.patch.object(web_steward, "_in_roster", lambda name: True):
            self.assertTrue(web_steward.http_project_upsert({"name": "zzz", "phase": "planned"})["ok"])
        self.assertTrue(web_steward.http_project_upsert({"name": "zzz", "phase": "paused"})["ok"])
        with sw.steward_lock("default"):
            st = sw.load_state("default")
            st["shutdown"] = {"started": 1.0, "only": ["zzz"], "init": True, "items": {}, "prev_phase": {"zzz": "planned"}}
            sw.save_state(st, "default")
        res = web_steward.shutdown_tick("default", views=[])
        self.assertTrue(res["done"])
        sd = sw.load_state("default")["shutdown"]
        self.assertEqual(sd["left_paused"], ["zzz"])
        ev = [e for e in sw.tail_log(20) if e["event"] == "shutdown_done"][-1]
        self.assertEqual(ev["left_paused"], ["zzz"])
        self.assertIn("steward set", ev["hint"])
        self.assertEqual(web_steward.http_state("default")["shutdown"]["left_paused"], ["zzz"])
        self.assertEqual(sw.load_projects()["zzz"].phase, "paused")        # faz geri yüklenmedi


class BrainCannotPauseTest(_Tmp):
    def test_brain_cannot_pause_or_done_but_owner_can(self):
        with mock.patch.object(web_steward, "_in_roster", lambda name: True):
            self.assertTrue(web_steward.http_project_upsert({"name": "zzz", "phase": "planned"})["ok"])
            for ph in ("paused", "done", "idea"):      # idea da aktif fazdan çıkıştır: kapıyı aşamaz
                r = web_steward.http_project_upsert({"name": "zzz", "phase": ph, "actor": "brain"})
                self.assertFalse(r["ok"], ph)
            self.assertEqual(sw.load_projects()["zzz"].phase, "planned")
            self.assertTrue(web_steward.http_project_upsert({"name": "zzz", "notes": "x", "actor": "brain"})["ok"])
            self.assertTrue(web_steward.http_project_upsert({"name": "zzz", "phase": "paused"})["ok"])    # insan/CLI serbest


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


class ReviewFindings20261029Test(_Tmp):
    """TODO 2026-10-28 (21): JOB isteği kopya sayılmaz; DONE/PLAN-READY düzyazıda tetiklenmez; OWNER_ONLY sahte pozitifleri."""

    def test_job_requests_for_different_files_are_not_merged(self):
        a, how_a = sw.add_question_ex("p", sw.JOB_REQUEST_PREFIX + "embed docs/requests/A1_import.md A1 bölümü", routine=True)
        b, how_b = sw.add_question_ex("p", sw.JOB_REQUEST_PREFIX + "embed docs/requests/A2_import.md A1 bölümü", routine=True)
        self.assertEqual((how_a, how_b), ("new", "new"))
        self.assertNotEqual(a.id, b.id)

    def test_done_and_plan_ready_in_prose_are_ignored(self):
        for text in ("`STEWARD-DONE` yazmıyorum, iş kaldı.", "NO-STEWARD-DONE etiketi notta var."):
            self.assertFalse(sw.scan_markers(text)["done"], text)
        self.assertFalse(sw.scan_markers("STEWARD-PLAN-READY yazmadan önce PLAN.md'yi bitireceğim.")["plan_ready"])
        self.assertTrue(sw.scan_markers("bitti\nSTEWARD-DONE")["done"])
        self.assertTrue(sw.scan_markers("- STEWARD-DONE: kanıt")["done"])
        self.assertTrue(sw.scan_markers("`STEWARD-PLAN-READY`")["plan_ready"])

    def test_owner_only_false_positives(self):
        for t in ("Qdrant koleksiyonu kuruldu mu?", "bağlam token'ı 200K, alt ajan açayım mı?", "silsile tablosunu yeniden üretsem?",
                  "workforce raporu"):
            self.assertIsNone(sw.OWNER_ONLY_RE.search(t), t)
        for t in ("git push --force yapayım mı", "dosyayı sileyim mi", "API token ver", "apt install x", "parolayı gir"):
            self.assertIsNotNone(sw.OWNER_ONLY_RE.search(t), t)


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


class TopicMergeTest(_Tmp):
    """L7 (10 Kas): aynı KONU farklı anlatımla yeniden sorulunca (kelime Jaccard'ı düşük) sahip yeniden rahatsız edilmez."""

    V1 = ("Survey İngilizce taslağı (`main.tex` ve `main.pdf`, 22 sayfa) yayına hazır. Sahipte kalan kararlar: (1) Gedik "
          "ve Bogazici bağlılıkları, (2) T-1 kod kararı, (3) hedef dergi. Ne yapalım?")
    V2 = ("TODO T5'te sahibin kararı bekleyen dört şey var. Hepsi için `main.pdf` (27 sayfa, tam metin doğrulanmış) hazır. "
          "(1) Kurum adları: `main.tex`te Gedik ve Bogazici taslak yazıldı. (2) T-1 kod adayı. Onaylıyor musunuz?")

    def test_topic_tokens(self):
        t = sw.topic_tokens(self.V2)
        self.assertTrue({"main.pdf", "main.tex", "t5", "t-1", "gedik", "bogazici"} <= t, t)
        self.assertNotIn("hepsi", t)

    def test_generic_names_alone_do_not_match(self):
        a = sw.topic_tokens("Canlı yolda Python mu kalsın, Rust gölgede mi çalışsın?")
        b = sw.topic_tokens("Ön-aggregation katmanını Python ile mi Rust ile mi yazalım?")
        self.assertEqual(sw.topic_match(a, b), 0.0)

    def test_open_question_rephrased_is_merged_and_keeps_old_text(self):
        q1, how1 = sw.add_question_ex("vesuviusppr", self.V1, source="vesuviusppr20261107")
        q2, how2 = sw.add_question_ex("vesuviusppr", self.V2, source="vesuviusppr20261107_1")
        self.assertEqual((how1, how2, q2.id), ("new", "merged", q1.id))
        got = sw.find_question(q1.id)
        self.assertEqual(got.text, self.V2)                       # en yeni sürüm görünür
        self.assertEqual(got.prev_texts, [self.V1])               # eskisi kaybolmaz
        self.assertEqual(got.source, "vesuviusppr20261107_1")     # cevap yeni soranın oturumuna
        self.assertEqual(len(sw.open_questions()), 1)
        html_text = sw.question_page_html(got)
        self.assertIn("Aynı konuda önceki sürümler (1)", html_text)

    def test_hold_answer_suppresses_same_topic(self):
        q1 = sw.add_question("vesuviusppr", self.V1)
        sw.answer_question(q1.id, "Sahip main.pdf'i okuyacak; kararlar okuduktan sonra gelecek, bekle.")
        q2, how = sw.add_question_ex("vesuviusppr", self.V2)
        self.assertEqual((q2.id, how), (q1.id, "reasked"))
        self.assertEqual(sw.find_question(q1.id).repeats, 1)

    def test_non_hold_answer_lets_new_decision_open(self):
        q1 = sw.add_question("vesuviusppr", self.V1)
        sw.answer_question(q1.id, "A: tam survey taslağına geç.")     # karar verildi: aynı konuda YENİ karar sorulabilir
        q2, how = sw.add_question_ex("vesuviusppr", self.V2)
        self.assertEqual(how, "new")
        self.assertNotEqual(q2.id, q1.id)

    def test_old_open_question_outside_window_not_merged(self):
        q1 = sw.add_question("vesuviusppr", self.V1)
        qs = sw.load_questions()
        qs[0].created_at -= sw.TOPIC_OPEN_WINDOW_SECONDS + 60
        sw.save_questions(qs)
        q2, how = sw.add_question_ex("vesuviusppr", self.V2)
        self.assertEqual(how, "new")

    def test_other_project_not_merged(self):
        a = sw.add_question("vesuviusppr", self.V1)
        b = sw.add_question("animallangppr", self.V2)
        self.assertNotEqual(a.id, b.id)


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
        v = _view("p1", last_assistant="iş bitti\nSTEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt", subagent_active=True)
        acts, st = sw.plan_tick([v], projects, {}, _cfg(), 5000.0, [], [])
        self.assertEqual([a for a in acts if a.kind in ("set_phase", "stop")], [])
        self.assertEqual(st["done_pending"], {"p1": "p1"})
        v2 = _view("p1", last_assistant="iş bitti\nSTEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt", subagent_active=False)
        acts, st = sw.plan_tick([v2], projects, st, _cfg(), 5200.0, [], [])
        self.assertEqual([(a.kind, a.name) for a in acts if a.kind in ("set_phase", "stop")], [("set_phase", "p1"), ("stop", "p1")])
        self.assertNotIn("done_pending", st)

    def test_deferred_done_dropped_when_no_done_tag_added_later(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        acts, st = sw.plan_tick([_view("p1", last_assistant="iş bitti\nSTEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt", subagent_active=True)],
                                projects, {}, _cfg(), 5000.0, [], [])
        self.assertEqual(st["done_pending"], {"p1": "p1"})
        projects["p1"].notes = "sürekli geliştirme " + sw.NO_DONE_TAG
        acts, st = sw.plan_tick([_view("p1", last_assistant="iş bitti\nSTEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt", subagent_active=False)],
                                projects, st, _cfg(), 5200.0, [], [])
        self.assertEqual([a for a in acts if a.kind in ("set_phase", "stop")], [])
        self.assertNotIn("done_pending", st)

    def test_done_immediate_without_subagent(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        acts, _ = sw.plan_tick([_view("p1", last_assistant="STEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt")], projects, {}, _cfg(), 5000.0, [], [])
        self.assertEqual([a.kind for a in acts if a.kind in ("set_phase", "stop")], ["set_phase", "stop"])


class AnswerStartPhaseTest(unittest.TestCase):
    """Eski iletilmemiş cevap `answer → start` ile YALNIZ aktif fazdaki (planning/planned) projeyi açar; paused/done açılmaz."""
    def _plan(self, phase):
        q = sw.Question(id="q1", project="p1", text="soru?", created_at=1000.0, status="answered", answer="evet", answered_at=2000.0)
        projects = {"p1": sw.Project(name="p1", phase=phase, cadence_minutes=60)}
        acts, _ = sw.plan_tick([], projects, {}, _cfg(), 5000.0, [q], [])
        return [(a.kind, a.name) for a in acts if a.kind in ("start", "deliver_answer", "set_phase")]

    def test_active_phase_starts(self):
        self.assertEqual(self._plan("planned"), [("start", "p1")])

    def test_owner_answer_reopens_paused_and_done_project(self):
        """17 Kas (sahip, marwan): sahip cevabı done/paused projeyi planned'a çeker ve açar (eskiden cevap iletilmeden bekliyordu)."""
        for phase in ("paused", "done"):
            self.assertEqual(self._plan(phase), [("set_phase", "p1"), ("start", "p1")], phase)


class NegativeAnswerTest(unittest.TestCase):
    """21 Kas: 'Hayır, paused kalsın' gibi olumsuz/bekle cevabı done/paused projeyi planned'a ÇEKMEZ ve açmaz (wifi5gppr/fotocizimppr)."""
    def test_is_negative_answer(self):
        for t in ("Hayır, paused kalsın", "hayır", "No", "açma", "Bekle", "Paused kalsın", "şimdi değil", "sonra bakarız", "Hayır."):
            self.assertTrue(sw.is_negative_answer(t), t)
        for t in ("Aç", "evet", "Evet, aç", "", "Hayır ama şu TODO maddesini yap: " + "x" * 80, "devam et", "Hayırlısı olsun yap"):
            self.assertFalse(sw.is_negative_answer(t), t)

    def _plan(self, phase, answer):
        q = sw.Question(id="q1", project="p1", text="soru?", created_at=1000.0, status="answered", answer=answer, answered_at=2000.0)
        projects = {"p1": sw.Project(name="p1", phase=phase, cadence_minutes=60)}
        acts, _ = sw.plan_tick([], projects, {}, _cfg(), 5000.0, [q], [])
        return [(a.kind, a.name) for a in acts if a.kind in ("start", "deliver_answer", "set_phase", "close_negative_answer")]

    def test_negative_answer_does_not_reopen(self):
        for phase in ("paused", "done"):
            self.assertEqual(self._plan(phase, "Hayır, paused kalsın"), [("close_negative_answer", "p1")], phase)
            self.assertEqual(self._plan(phase, "Aç"), [("set_phase", "p1"), ("start", "p1")], phase)

    def test_hold_answers_real_texts_do_not_reopen(self):
        """22 Kas: sahip adına verilen uzun 'tut' cevapları paused projeyi açmamalı; olumlular açmalı."""
        holds = ("TBD de kalsin, ILL/yazar istegi YAPMA, kaynaklar elde olanla devam", "2) Paused kalsin. Kota sifirlaninca yeniden sorulsun",
                 "Faz paused kalsin, yuhem gelene dek", "istenmesin", "yuhem gelene dek bekle", "bilmiyorum", "claude")
        for t in holds:
            self.assertFalse(sw.is_open_answer(t), t)
            self.assertEqual(self._plan("paused", t), [("close_negative_answer", "p1")], t)
        for t in ("Aç", "1) Aç", "evet", "Evet, aç; Sonnet ile", "planned yap", "başla", "Sonnet ile aç"):
            self.assertTrue(sw.is_open_answer(t), t)
            self.assertEqual(self._plan("paused", t), [("set_phase", "p1"), ("start", "p1")], t)

    def test_sweep_question_has_options(self):
        projects = {"c": sw.Project(name="c", phase="paused", cadence_minutes=60)}
        acts, _ = sw.plan_tick([], projects, {"todo_seen": {"c": "h1"}}, _cfg(), 200000.0, [], [], open_work=lambda n: 3, todo_sha=lambda n: "h1")
        asks = [a for a in acts if a.kind == "ask_user"]
        self.assertEqual(asks[0].payload["options"], ["Aç", "Paused kalsın"])


class DoneHandoverTest(unittest.TestCase):
    """STEWARD-DONE-CONFIRMED: teyit -> faz done -> DEVİR (READY FOR HANDOVER) -> stop (yeniden açma YOK); küçük bağlamda
    devir atlanır; sahip 'çelişti' cevabı yeniden soru açtırmaz, 'bitti' ise sayı çelişkisi sayılmaz."""
    OK = "bitti\nSTEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, testler yeşil"

    def _cfg(self, **kw):
        c = _cfg(**kw)
        c.done_handover = True
        return c

    def _projects(self):
        return {"p1": sw.Project(name="p1", phase="planned")}

    def _k(self, acts):
        return [(a.kind, a.name) for a in acts if a.kind in ("set_phase", "stop", "handover", "respawn", "ask_user")]

    def test_done_hands_over_then_stops_never_respawns(self):
        acts, st = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, self._cfg(), 5000.0, [], [])
        self.assertEqual(self._k(acts), [("set_phase", "p1"), ("handover", "p1")])
        self.assertEqual(st["ho_close"], {"p1": "p1"})
        self.assertIn("p1", st["ho_pending"])
        acts, st2 = sw.plan_tick([_view("p1", last_assistant="devir\n" + sw.READY_FOR_HANDOVER, busy=False)],
                                 self._projects(), st, self._cfg(), 5100.0, [], [])
        self.assertEqual([(a.kind, a.name) for a in acts if a.kind in ("stop", "respawn")], [("stop", "p1")])
        self.assertNotIn("ho_close", st2)
        self.assertNotIn("p1", st2.get("ho_pending", {}))

    def test_session_gone_during_done_handover_is_not_respawned(self):
        _, st = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, self._cfg(), 5000.0, [], [])
        acts, st2 = sw.plan_tick([], self._projects(), st, self._cfg(), 5100.0, [], [])
        self.assertEqual([a for a in acts if a.kind == "respawn"], [])
        self.assertNotIn("ho_close", st2)

    def test_grace_expiry_still_stops(self):
        cfg = self._cfg()
        _, st = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, cfg, 5000.0, [], [])
        acts, _ = sw.plan_tick([_view("p1", last_assistant="hâlâ yazıyor", busy=False)], self._projects(), st, cfg,
                               5000.0 + cfg.ho_grace_minutes * 60 + 1, [], [])
        self.assertEqual([(a.kind, a.name) for a in acts if a.kind in ("stop", "respawn")], [("stop", "p1")])

    def test_small_context_skips_handover(self):
        cfg = self._cfg(context_warn_tokens=300000)
        acts, st = sw.plan_tick([_view("p1", last_assistant=self.OK, context_tokens=20000)], self._projects(), {}, cfg, 5000.0, [], [])
        self.assertEqual(self._k(acts), [("set_phase", "p1"), ("stop", "p1")])
        self.assertNotIn("ho_close", st)
        acts, st = sw.plan_tick([_view("p1", last_assistant=self.OK, context_tokens=200000)], self._projects(), {}, cfg, 5000.0, [], [])
        self.assertEqual(self._k(acts), [("set_phase", "p1"), ("handover", "p1")])

    def test_switch_off_is_old_direct_stop(self):
        cfg = self._cfg()
        cfg.done_handover = False
        acts, _ = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, cfg, 5000.0, [], [])
        self.assertEqual(self._k(acts), [("set_phase", "p1"), ("stop", "p1")])

    def test_owner_answer_stops_reasking_and_bitti_closes(self):
        q = sw.Question(id="q1", project="p1", text="p1: STEWARD-DONE-CONFIRMED geldi ama TODO.md'de 410 açık iş var", created_at=1000.0,
                        status="answered", answer="bitti, kapat", answered_at=4000.0)
        acts, _ = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, self._cfg(), 5000.0, [q], [],
                               open_work=lambda proj: 410)
        self.assertEqual(self._k(acts), [("set_phase", "p1"), ("handover", "p1")])       # 'bitti': sayı çelişkisi sayılmaz
        q.answer = "hayır, devam et"
        acts, _ = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, self._cfg(), 5000.0, [q], [],
                               open_work=lambda proj: 410)
        self.assertEqual(self._k(acts), [])                                               # yeniden 'çelişti' sorusu YOK, kapanış da yok
        acts, _ = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, self._cfg(), 5000.0 + sw.DONE_ANSWER_TTL, [q], [],
                               open_work=lambda proj: 410)
        self.assertEqual(self._k(acts), [("ask_user", "p1")])                             # cevap eskidi: yeniden sorulabilir

    def test_unknown_open_work_symlinked_worktree_accepts_proof(self):
        """open_work None (TODO.md başka projenin symlink'i, `_todo_owned_by_other`): sayı çelişkisi YOK, kanıtlı teyit kabul (soru açılmaz)."""
        cfg = self._cfg()
        acts, _ = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, cfg, 5000.0, [], [], open_work=lambda proj: None)
        self.assertNotIn("ask_user", [a.kind for a in acts])
        self.assertIn("set_phase", [a.kind for a in acts])

    def test_unanswered_conflict_still_asks(self):
        acts, _ = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, self._cfg(), 5000.0, [], [],
                               open_work=lambda proj: 410)
        self.assertEqual(self._k(acts), [("ask_user", "p1")])


class DoneConfirmTest(unittest.TestCase):
    """STEWARD-DONE iki adımlı (sahip kararı 2026-10-25): düz DONE = iddia -> tek teyit direktifi, faz/oturum değişmez;
    yalnız kanıtlı STEWARD-DONE-CONFIRMED fazı done yapar ve durdurur."""
    OK = "bitti\nSTEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, testler yeşil"

    def _projects(self, **kw):
        return {"p1": sw.Project(name="p1", phase="planned", **kw)}

    def _kinds(self, acts):
        return [(a.kind, a.name) for a in acts if a.kind in ("set_phase", "stop", "nudge", "ask_user")]

    def test_plain_done_asks_for_confirmation_and_keeps_phase(self):
        acts, st = sw.plan_tick([_view("p1", last_assistant="parça 5 bitti\nSTEWARD-DONE")], self._projects(), {}, _cfg(), 5000.0, [], [])
        self.assertEqual(self._kinds(acts), [("nudge", "p1")])
        n = [a for a in acts if a.kind == "nudge"][0]
        self.assertTrue(n.payload["confirm"])
        self.assertIn("STEWARD-DONE-CONFIRMED", n.payload["text"])
        self.assertEqual(st["done_confirm"], {"p1": 5000.0})

    def test_second_plain_done_does_not_spam_but_ttl_reasks(self):
        projects = self._projects()
        _, st = sw.plan_tick([_view("p1", last_assistant="a\nSTEWARD-DONE")], projects, {}, _cfg(), 5000.0, [], [])
        acts, st = sw.plan_tick([_view("p1", last_assistant="b\nSTEWARD-DONE")], projects, st, _cfg(), 5200.0, [], [])
        self.assertEqual(self._kinds(acts), [])
        acts, st = sw.plan_tick([_view("p1", last_assistant="c\nSTEWARD-DONE")], projects, st, _cfg(), 5000.0 + sw.DONE_CONFIRM_TTL + 1, [], [])
        self.assertEqual(self._kinds(acts), [("nudge", "p1")])

    def test_confirmed_with_evidence_sets_done_and_stops(self):
        acts, st = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {"done_confirm": {"p1": 4900.0}}, _cfg(), 5000.0, [], [])
        self.assertEqual(self._kinds(acts), [("set_phase", "p1"), ("stop", "p1")])
        self.assertNotIn("done_confirm", st)

    def test_confirmed_without_evidence_is_not_done(self):
        for body in ("STEWARD-DONE-CONFIRMED:", "STEWARD-DONE-CONFIRMED: bitti", "STEWARD-DONE-CONFIRMED: abc1234 kalan 3 iş"):
            acts, _ = sw.plan_tick([_view("p1", last_assistant=body)], self._projects(), {}, _cfg(), 5000.0, [], [])
            self.assertEqual([k for k, _n in self._kinds(acts) if k in ("set_phase", "stop")], [], body)
            self.assertEqual(self._kinds(acts), [("nudge", "p1")], body)

    def test_confirmed_but_local_open_work_asks_owner_not_done(self):
        acts, _ = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, _cfg(), 5000.0, [], [],
                               open_work=lambda proj: 4)
        self.assertEqual(self._kinds(acts), [("ask_user", "p1")])
        self.assertIn("4 açık", [a for a in acts if a.kind == "ask_user"][0].payload["text"])
        acts, _ = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, _cfg(), 5000.0, [], [],
                               open_work=lambda proj: 0)
        self.assertEqual(self._kinds(acts), [("set_phase", "p1"), ("stop", "p1")])
        acts, _ = sw.plan_tick([_view("p1", last_assistant=self.OK)], self._projects(), {}, _cfg(), 5000.0, [], [],
                               open_work=lambda proj: None)      # uzak/okunamayan: kanıta kalır
        self.assertEqual(self._kinds(acts), [("set_phase", "p1"), ("stop", "p1")])

    def test_no_steward_done_tag_ignores_both_markers(self):
        for text in ("STEWARD-DONE", self.OK):
            acts, st = sw.plan_tick([_view("p1", last_assistant=text)], self._projects(notes="sürekli " + sw.NO_DONE_TAG), {}, _cfg(), 5000.0, [], [])
            self.assertEqual(self._kinds(acts), [])
            self.assertNotIn("done_confirm", st)

    def test_confirm_marker_is_not_plain_done_and_placeholder_ignored(self):
        self.assertFalse(sw.scan_markers("STEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0")["done"])
        self.assertEqual(sw.scan_markers("STEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0")["confirmed"], "abc1234 kalan açık iş 0")
        for echo in ("`STEWARD-DONE-CONFIRMED: <son commit kısa hash> kalan açık iş 0, <kanıt>` yaz", "> STEWARD-DONE-CONFIRMED: abc1234 0"):
            m = sw.scan_markers(echo)
            self.assertIsNone(m["confirmed"], echo)
            self.assertFalse(m["done"], echo)

    def test_subagent_active_defers_confirmed(self):
        acts, st = sw.plan_tick([_view("p1", last_assistant=self.OK, subagent_active=True)], self._projects(), {}, _cfg(), 5000.0, [], [])
        self.assertEqual(self._kinds(acts), [])
        self.assertEqual(st["done_pending"], {"p1": "p1"})

    def test_open_work_of_counts_local_todo(self):
        import tempfile
        from claudeops.commands import web_steward as ws
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "TODO.md"), "w", encoding="utf-8") as f:
                f.write("- [ ] a\n* [ ] b\n- [x] c\n  - [ ] d\ntext - [ ] not a task\n- [ ] e: SAHİBE SORULDU, cevap gelene dek uygulanmaz\n")
            projs = {"p1": sw.Project(name="p1", phase="planned"), "r": sw.Project(name="r", phase="planned", host="ulak_31")}
            with mock.patch.object(ws, "_cwd_resolver", lambda: (lambda n: d)):
                f = ws._open_work_of(projs)
                self.assertEqual(f("p1"), 3)
                self.assertIsNone(f("r"))          # uzak: ön-kontrol yok
                self.assertIsNone(f("yok"))
            with mock.patch.object(ws, "_cwd_resolver", lambda: (lambda n: os.path.join(d, "yok"))):
                self.assertIsNone(ws._open_work_of(projs)("p1"))

    def test_open_tbd_of_falls_back_to_main_worktree(self):
        import subprocess, tempfile
        from claudeops.commands import web_steward as ws
        with tempfile.TemporaryDirectory() as d:
            main, wt = os.path.join(d, "main"), os.path.join(d, "wt")
            os.makedirs(main)
            git = lambda *a, cwd=main: subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True,
                                                      capture_output=True)
            git("init", "-q", "-b", "main")
            with open(os.path.join(main, "TOBEDECIDED.md"), "w", encoding="utf-8") as f:
                f.write("## Açık\n### 1) karar\n### 2) karar\n")
            with open(os.path.join(main, "TODO.md"), "w", encoding="utf-8") as f:
                f.write("- [x] bitti\n")
            git("add", "."); git("commit", "-q", "-m", "x")
            git("worktree", "add", "-q", wt, "-b", "wtb")
            os.remove(os.path.join(wt, "TOBEDECIDED.md"))        # worktree'de dosya yok
            projs = {"p": sw.Project(name="p", phase="planned")}
            with mock.patch.object(ws, "_cwd_resolver", lambda: (lambda n: wt)):
                self.assertEqual(ws._open_tbd_of(projs)("p"), 2)        # ana worktree'deki dosya sayılır
                self.assertEqual(ws._open_work_of(projs)("p"), 0)
            with mock.patch.object(ws, "_cwd_resolver", lambda: (lambda n: d)):
                self.assertIsNone(ws._open_tbd_of(projs)("p"))           # git deposu değil, dosya yok: bilinmiyor


class TourQuietTest(unittest.TestCase):
    """TBD#122: beynin skip ettiği ve durumu değişmeyen madde yeniden tura girmez; bayat blokaj kaydı kapanır."""

    def _items(self, views, projects, qs, now, skip_seen=None, sigs=None):
        return sw.review_items(views, projects, _cfg(), now, qs, [], skip_seen=skip_seen, sigs_out=sigs)

    def test_skipped_unchanged_item_stays_out_until_state_changes_or_ttl(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        now = 100000.0
        v = _view("p1", busy=False, last_activity=1.0, started_at=1.0, last_assistant="x")
        sigs = {}
        self.assertEqual([i["kind"] for i in self._items([v], projects, [], now, sigs=sigs)], ["idle"])
        seen = {"p1": {"at": now, "sig": sigs["p1"]}}
        self.assertEqual(self._items([v], projects, [], now + 1200, skip_seen=seen), [])               # değişmedi: sessiz
        v2 = _view("p1", busy=False, last_activity=1.0, started_at=1.0, last_assistant="yeni çıktı")
        self.assertEqual(len(self._items([v2], projects, [], now + 1200, skip_seen=seen)), 1)           # çıktı değişti
        q = sw.Question(id="q1", project="p1", text="?", created_at=now, status="answered", answer="a", delivered_at=now, source="p1")
        self.assertEqual(len(self._items([v], projects, [q], now + 1200, skip_seen=seen)), 1)           # yeni cevap
        self.assertEqual(len(self._items([v], projects, [], now + sw.SKIP_QUIET_SECONDS + 1, skip_seen=seen)), 1)   # süre doldu

    def test_plan_tick_records_tour_sig_and_honors_skip_seen(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        brain = _view("degnekci", busy=False)
        v = _view("p1", busy=False, last_activity=1.0, started_at=1.0, last_assistant="x")
        cfg = _cfg(brain_name="degnekci")
        acts, st = sw.plan_tick([brain, v], projects, {}, cfg, 100000.0, [], [])
        self.assertTrue(any(a.kind == "tour" for a in acts))
        self.assertIn("p1", st["tour_sig"])
        st["skip_seen"] = {"p1": {"at": 100000.0, "sig": st["tour_sig"]["p1"]}}
        st["last_tour"] = 0.0
        acts, st2 = sw.plan_tick([brain, v], projects, st, cfg, 101500.0, [], [])
        self.assertFalse(any(a.kind == "tour" for a in acts))
        self.assertIn("p1", st2["skip_seen"])

    def test_stale_undelivered_answer_closed_not_toured(self):
        projects = {"cli": sw.Project(name="cli", phase="planned")}
        now = 1_000_000.0
        q = sw.Question(id="q1", project="cli20261021", text="?", created_at=now - 9 * 3600, status="answered", answer="a",
                        answered_at=now - 8 * 3600, source="brain")
        self.assertEqual([i for i in self._items([], projects, [q], now) if i["kind"] == "blocked"], [])
        acts, _ = sw.plan_tick([], projects, {}, _cfg(), now, [q], [])
        self.assertEqual([(a.kind, a.payload["question_id"]) for a in acts if a.kind == "close_stale_answer"], [("close_stale_answer", "q1")])
        fresh = sw.Question(id="q2", project="cli20261021", text="?", created_at=now - 100, status="answered", answer="a",
                            answered_at=now - 50, source="brain")
        self.assertEqual(len([i for i in self._items([], projects, [fresh], now) if i["kind"] == "blocked"]), 1)    # taze: hâlâ madde
        live = _view("cli20261021", busy=True)
        acts, _ = sw.plan_tick([live], projects, {}, _cfg(), now, [q], [])
        self.assertFalse(any(a.kind == "close_stale_answer" for a in acts))                                         # soran canlı: iletilebilir

    def test_projectless_answer_closes_when_brain_never_runs(self):
        # 12 Kas: reviewer kimliğinde beyin turu yok; 24-28 Eki'den 3 projesiz "Tamam" bildirimi sonsuza dek `blocked` kaldı
        now = 1_000_000.0
        cfg = _cfg()
        q = sw.Question(id="q1", project="", text="review saklama", created_at=now - 9 * 3600, status="answered", answer="Tamam",
                        answered_at=now - 8 * 3600, source="reviewer-store")
        acts, _ = sw.plan_tick([], {}, {}, cfg, now, [q], [])
        self.assertEqual([a.payload["question_id"] for a in acts if a.kind == "close_stale_answer"], ["q1"])
        fresh = sw.Question(id="q2", project="", text="?", created_at=now - 100, status="answered", answer="a", answered_at=now - 50)
        acts, _ = sw.plan_tick([], {}, {}, cfg, now, [fresh], [])
        self.assertFalse(any(a.kind == "close_stale_answer" for a in acts))           # taze: bekler
        brain = _view(cfg.brain_name, busy=True)
        self.assertEqual(sw.stale_answers([q], {}, cfg, now, {brain.name}), [])        # beyin canlı: tur yolu (BLOCKED_MAX_TOURS) kapatır

    def test_brain_question_answer_goes_to_live_session_named_by_project(self):
        # 2026-10-27: beyin `hof20261026` (tarihli oturum adı) için sordu (source=brain); cevap hiç iletilmeyip her turda 'blocked' oldu
        projects = {"hof": sw.Project(name="hof", phase="planned")}
        now = 1_000_000.0
        q = sw.Question(id="q1", project="hof20261026", text="?", created_at=now - 100, status="answered", answer="evet",
                        answered_at=now - 50, source="brain")
        live = _view("hof20261026", busy=False)
        acts, _ = sw.plan_tick([live], projects, {}, _cfg(), now, [q], [])
        self.assertEqual([(a.kind, a.name) for a in acts if a.kind == "deliver_answer"], [("deliver_answer", "hof20261026")])

    def test_keepwarm_ok_does_not_change_the_item_signature_and_routine_carries_age(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        v1 = _view("p1", last_assistant="ok")
        v2 = _view("p1", last_assistant="Ok.")
        v3 = _view("p1", last_assistant="gerçek çıktı")
        self.assertEqual(sw.item_signature(v1, projects, []), sw.item_signature(v2, projects, []))
        self.assertNotEqual(sw.item_signature(v1, projects, []), sw.item_signature(v3, projects, []))
        now = 1_000_000.0
        q = sw.Question(id="r1", project="p1", text="Opus ne zaman?", created_at=now - 25 * 60, routine=True)
        items = sw.review_items([], projects, _cfg(), now, [q], [])
        it = [i for i in items if i["kind"] == "routine"][0]
        self.assertEqual(it["age_min"], 25)
        self.assertIn("25 dk önce", it["text"])

    def test_observe_tour_does_not_burn_blocked_tour_budget(self):
        # TODO 2026-10-28 (21): observe'ta tur uygulanmaz ama sayaç artıyordu: cevap 2 kuru turda undeliverable kapanırdı
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        now = 1_000_000.0
        q = sw.Question(id="q1", project="", text="?", created_at=now - 100, status="answered", answer="a",
                        answered_at=now - 50, source="brain")
        brain = _view("degnekci", busy=False)
        cfg = _cfg(brain_name="degnekci", mode="observe")
        st: dict = {}
        for _ in range(sw.BLOCKED_MAX_TOURS + 2):
            acts, st = sw.plan_tick([brain], projects, st, cfg, now, [q], [])
            apply, dry, st = sw.observe_filter(acts, "observe", st, now)
            self.assertFalse(any(a.kind == "close_stale_answer" for a in apply))
            now += cfg.tour_minutes * 60 + sw.OBSERVE_DEDUP_SECONDS + 1
        self.assertNotIn("blocked_tours", st)

    def test_pending_count_is_the_full_list_even_when_a_tour_is_sent(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        now = 1_000_000.0
        qs = [sw.Question(id=f"q{i}", project="", text="?", created_at=now - 100, status="answered", answer="a",
                          answered_at=now - 50, source="brain") for i in range(12)]
        brain = _view("degnekci", busy=False)
        acts, st = sw.plan_tick([brain], projects, {}, _cfg(brain_name="degnekci"), now, qs, [])
        self.assertTrue(any(a.kind == "tour" for a in acts))
        self.assertEqual(st["pending_items"], len(st["pending_list"]))
        self.assertGreater(st["pending_items"], sw.TOUR_MAX_ITEMS)

    def test_count_open_tbd_new_format_needs_an_AÇIK_heading(self):
        txt = ("## Açık\n\n### 1) soru\n\n## 2026-10-25 TBD#116: kota\nKARAR yok ama işaret de yok\n\n"
               "## 2026-10-29 TBD#141: AÇIK ne yapalım?\n")
        self.assertEqual(sw.count_open_tbd(txt), 2)           # `### 1)` + AÇIK başlıklı yeni biçim; işaretsiz yenisi sayılmaz
        self.assertEqual(sw.count_open_tbd("## Açık\n\n## 2026-10-29 TBD#141: KARAR AÇIK\n"), 0)   # KARAR işareti kapatır

    def test_shutdown_unknown_activity_waits_unless_idle(self):
        cfg = sw.Config()
        projects = {"ncs": sw.Project(name="ncs")}
        for busy, expect in ((None, []), (True, []), (False, ["handover"])):
            v = sw.SessionView(name="ncs", running=True, cwd="/x", cli="claude", busy=busy, last_activity=0.0)
            acts, _sd, _d = sw.plan_shutdown([v], projects, {}, cfg, 1000.0)
            self.assertEqual([a.kind for a in acts], expect, busy)

    def test_blocked_item_closed_after_max_tours_not_urgent_again(self):
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        now = 1_000_000.0
        q = sw.Question(id="q1", project="", text="?", created_at=now - 100, status="answered", answer="a",
                        answered_at=now - 50, source="brain")
        brain = _view("degnekci", busy=False)
        cfg = _cfg(brain_name="degnekci")
        st: dict = {}
        for n in range(sw.BLOCKED_MAX_TOURS):
            acts, st = sw.plan_tick([brain], projects, st, cfg, now, [q], [])
            self.assertEqual([a.kind for a in acts if a.kind == "tour"], ["tour"])        # her tur madde gösterilir
            self.assertEqual(st["blocked_tours"]["q1"], n + 1)
            if n == 0:
                acts, st = sw.plan_tick([brain], projects, st, cfg, now + 61, [q], [])
                self.assertFalse(any(a.kind == "tour" for a in acts))                       # YALNIZ ilk görünüş 60 sn acildir
            now += cfg.tour_minutes * 60 + 1
        acts, st = sw.plan_tick([brain], projects, st, cfg, now, [q], [])
        self.assertFalse(any(a.kind == "tour" for a in acts))                               # artık tur yok
        closes = [a for a in acts if a.kind == "close_stale_answer"]
        self.assertEqual([a.payload["question_id"] for a in closes], ["q1"])
        self.assertTrue(closes[0].payload["reason"])
        self.assertNotIn("blocked_tours", st)


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
        # cevapsız faz direktifi: aynı yaşamda kısa (başlık/not/protokol yok), faz talimatı korunur
        nb = sw.build_directive(p, compact=True)
        self.assertNotIn("Değnekçi protokolü", nb)
        self.assertNotIn("Amaç:", nb)
        self.assertIn("SIRADAKİ işi al", nb)
        self.assertIn("Değnekçi protokolü", sw.build_directive(p, compact=False))

    def test_directive_contains_all_answers(self):
        p = sw.Project(name="p1", phase="planned")
        msg = sw.build_directive(p, answer=self._q("a", "evet"), more=[self._q("b", "hayır")])
        self.assertIn("Cevabım: evet", msg)
        self.assertIn("soru b?", msg)
        self.assertIn("Cevabım: hayır", msg)


if __name__ == "__main__":
    unittest.main()

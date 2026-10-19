"""Değnekçi (steward) — çekirdek kurallar, depo, prompt'lar, ayar okuması, MCP araç adaptörü, HTTP katmanı
(stdlib unittest, canlı tmux/CLI YOK).

Çalıştırma:  python3 py/tests/test_steward.py -v
`CLAUDEOPS_DIR` geçici bir klasöre yönlendirilir (modül sabitleri patch'lenir), gerçek ayar/roster'a dokunmaz.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import mcp_queue, mcp_steward, web_steward  # noqa: E402
from claudeops.providers import get_provider  # noqa: E402
from claudeops.providers.base import CliProvider, OneshotError  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = self.dir.name
        sd = os.path.join(d, "steward")
        patches = [
            mock.patch.object(settings, "SETTINGS_JSON", os.path.join(d, "settings.json")),
            mock.patch.object(sw, "STEWARD_DIR", sd),
            mock.patch.object(sw, "PROJECTS_JSON", os.path.join(sd, "projects.json")),
            mock.patch.object(sw, "IDEAS_JSON", os.path.join(sd, "ideas.json")),
            mock.patch.object(sw, "QUESTIONS_JSON", os.path.join(sd, "questions.json")),
            mock.patch.object(sw, "STATE_JSON", os.path.join(sd, "state.json")),
            mock.patch.object(sw, "LOG_JSONL", os.path.join(sd, "log.jsonl")),
            mock.patch.object(sw, "WORKSPACE_DIR", os.path.join(sd, "workspace")),
            mock.patch.object(web_steward, "NTFY_TOPIC_FILE", os.path.join(d, "ntfy_topic.txt")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


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
        argv = get_provider("claude").oneshot_argv("özetle", "claude-haiku-4-5")
        self.assertEqual(argv[1:3], ["-p", "özetle"])      # prompt -p'den hemen sonra, variadic --tools'tan ÖNCE
        self.assertEqual(argv[-4:], ["--output-format", "text", "--tools", ""])
        self.assertEqual(argv[argv.index("--model") + 1], "claude-haiku-4-5")
        self.assertNotIn("--model", get_provider("claude").oneshot_argv("x", ""))
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
        for argv, kw in (([sys.executable, "-c", "import sys; sys.exit(3)"], {}),
                         ([sys.executable, "-c", "pass"], {}),                            # boş yanıt
                         ([sys.executable, "-c", "import time; time.sleep(5)"], {"timeout": 0.5}),
                         (["/yok/boyle/bir/ikili"], {})):
            with self.assertRaises(OneshotError, msg=str(argv)):
                run(argv, **kw)


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
        settings.save_settings({"steward": {"enabled": "on"}})
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


    def test_handover_route_marks_pending(self):
        self.assertTrue(web_steward.http_post("/api/steward/handover", {"name": "a"})["ok"])
        self.assertIn("a", sw.load_state()["ho_pending"])
        self.assertEqual(self.calls, [("handover", "a")])


if __name__ == "__main__":
    unittest.main()

"""Değnekçi (steward) — çekirdek kurallar, depo, prompt'lar, ayar okuması, MCP araç adaptörü, HTTP katmanı
(stdlib unittest, canlı tmux/CLI YOK).

Çalıştırma:  python3 py/tests/test_steward.py -v
`CLAUDEOPS_DIR` geçici bir klasöre yönlendirilir (modül sabitleri patch'lenir), gerçek ayar/roster'a dokunmaz.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings, steward as sw  # noqa: E402
from claudeops.commands import mcp_queue, mcp_steward, web_steward  # noqa: E402


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

    def test_handover_route_marks_pending(self):
        self.assertTrue(web_steward.http_post("/api/steward/handover", {"name": "a"})["ok"])
        self.assertIn("a", sw.load_state()["ho_pending"])
        self.assertEqual(self.calls, [("handover", "a")])


if __name__ == "__main__":
    unittest.main()

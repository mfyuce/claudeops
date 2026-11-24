"""Değnekçi testleri (test_steward.py bölünmüş parça: http). Çalıştırma: python3 -m pytest py/tests/test_steward_http.py"""
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


class HttpTest(_Tmp):
    def setUp(self):
        super().setUp()
        # tick_once kart adımını arka plan thread'inde koşturur: bir sonraki test `_CARD_LOCK`u tutulu bulup
        # kartı hiç üretmiyordu (dosya bütün koşunca kırılan flaky test). Testlerde iş satır içi koşsun.
        bg = mock.patch.object(web_steward, "_CARD_BACKGROUND", False)
        bg.start()
        self.addCleanup(bg.stop)
        web_steward._JOB_RED_SEEN.clear()      # süreç içi 24 sa RED belleği testler arası sızmasın (sıra bağımlı kırılma)
        self.addCleanup(web_steward._JOB_RED_SEEN.clear)
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
        self.assertEqual(len(web_steward.http_get("/api/steward/log", {"n": ["100"]})["entries"]), 7)

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
        done2 = _view("a", last_assistant="bitti\nSTEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt")
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: [done2]):
            r = web_steward.tick_once("timer")
        self.assertEqual([a["kind"] for a in r["actions"]], ["set_phase"])
        self.assertEqual([(d["kind"], d["name"]) for d in r["dry"]], [("handover", "a")])   # DONE: önce devir (done_handover), sonra stop

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
            # planned = işi var: beyin KAPATAMAZ (sahip kuralı 2026-11-01)
            self.assertFalse(web_steward.http_post("/api/steward/stop", {"name": "a", "actor": "brain"})["ok"])
            self.assertTrue(web_steward.http_post("/api/steward/stop", {"name": brain, "actor": "brain"})["ok"])
            self.assertTrue(web_steward.http_post("/api/steward/handover", {"name": "a", "actor": "brain"})["ok"])
            # paused = iş yok: öldürme değil, önce devir (ho_close), sonra motor kapatır
            sw.upsert_project("a", phase="paused")
            r = web_steward.http_post("/api/steward/stop", {"name": "a", "actor": "brain"})
            self.assertTrue(r["ok"])
            self.assertIn("a", sw.load_state().get("ho_close", {}))
        self.assertEqual(self.calls, [("stop", brain), ("handover", "a"), ("handover", "a")])

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


class JobRequestGateTest(HttpTest):
    """TBD#126: İŞ İSTEĞİ maddesi, beyin tarafından çıplak `devam` ile kapatılamaz (iş kaybolurdu)."""

    def _job_q(self):
        q, _ = sw.add_question_ex("mkt", sw.JOB_REQUEST_PREFIX + "ingest /x/REQ.md Sayoud2013", source="s", routine=True)
        return q

    def test_gate_pure(self):
        q = sw.Question(id="q1", project="mkt", text=sw.JOB_REQUEST_PREFIX + "ingest f", created_at=100.0, routine=True)
        job = {"project": "mkt", "created_at": 120.0}
        self.assertFalse(sw.job_request_gate(q, "devam", [])[0])
        self.assertFalse(sw.job_request_gate(q, "RED: kısa", [])[0])                          # gerekçe >= 12 karakter
        self.assertEqual(sw.job_request_gate(q, "RED: tür katalogda yok, ingest tanımsız", [])[::2], (True, "tür katalogda yok, ingest tanımsız"))
        self.assertTrue(sw.job_request_gate(q, "iş #7 queued", [job])[0])
        self.assertFalse(sw.job_request_gate(q, "iş #7", [{"project": "mkt", "created_at": 10.0}])[0])   # eski iş sayılmaz
        self.assertFalse(sw.job_request_gate(q, "iş #7", [{"project": "baska", "created_at": 120.0}])[0])
        plain = sw.Question(id="q2", project="mkt", text="Hangi sırayla?", created_at=1.0, routine=True)
        self.assertTrue(sw.job_request_gate(plain, "devam", [])[0])

    def test_brain_bare_devam_rejected_owner_allowed(self):
        q = self._job_q()
        r = web_steward.http_answer({"id": q.id, "answer": "devam", "actor": "brain"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "job_not_submitted")
        self.assertEqual(sw.open_questions()[0].id, q.id)               # madde açık kaldı
        self.assertTrue(web_steward.http_answer({"id": q.id, "answer": "devam"})["ok"])    # sahip (actor yok) kapatabilir

    def test_brain_red_closes_and_opens_owner_question(self):
        q = self._job_q()
        sent = []
        with mock.patch.object(web_steward, "_notify", lambda cfg, msg, *a, **k: sent.append(msg) or True):
            r = web_steward.http_answer({"id": q.id, "answer": "RED: ingest türü katalogda yok", "actor": "brain"})
        self.assertTrue(r["ok"])
        opened = [x for x in sw.open_questions() if x.source == "job-red"]
        self.assertEqual(len(opened), 1)
        self.assertFalse(opened[0].routine)                             # sahibe gider
        self.assertIn("katalogda yok", opened[0].text)
        self.assertTrue(any("katalogda yok" in m for m in sent))     # sahip sorusu telefona da gider

    def test_red_feedback_to_project_session_and_no_repeat_owner_question(self):
        """ncs 2026-10-29: RED oturuma gerekçe+geçerli türlerle iletilir; ardışık aynı RED sahibe tekrar sorulmaz."""
        web_steward._JOB_RED_SEEN.clear()
        self.addCleanup(web_steward._JOB_RED_SEEN.clear)
        proj = sw.Project(name="mkt")
        sent, notes = [], []
        reason = "RED: 'ocr' türü yok, ocr_script kullan"
        with mock.patch.object(web_steward, "_notify", lambda cfg, msg, *a, **k: notes.append(msg) or True), \
                mock.patch.object(sw, "load_projects", lambda sid="default": {"mkt": proj}), \
                mock.patch.object(web_steward, "_job_kinds_list", lambda sid: ["embed", "ocr_script"]), \
                mock.patch.object(web_steward, "_give_directive",
                                  lambda project, text, **kw: sent.append((project.name, text, kw)) or {"ok": True}):
            q1 = self._job_q()
            self.assertTrue(web_steward.http_answer({"id": q1.id, "answer": reason, "actor": "brain"})["ok"])
            q2, _ = sw.add_question_ex("mkt", sw.JOB_REQUEST_PREFIX + "ocr /x/REQ2.md baska", source="s", routine=True)
            self.assertTrue(web_steward.http_answer({"id": q2.id, "answer": reason, "actor": "brain"})["ok"])
        self.assertEqual(len(sent), 2)                                              # her iki RED oturuma gitti
        self.assertEqual(sent[0][0], "mkt")
        self.assertIn("ocr_script", sent[0][1])
        self.assertIn("embed, ocr_script", sent[0][1])
        self.assertFalse(sent[0][2]["start_if_stopped"])
        self.assertEqual(len([x for x in sw.open_questions() if x.source == "job-red"]), 1)   # sahip sorusu TEK
        self.assertEqual(len(notes), 1)

    def test_job_kinds_list_shapes(self):
        for body, want in (({"kinds": ["b", "a"]}, ["a", "b"]), ({"kinds": {"x": 1, "y": 2}}, ["x", "y"]),
                           ([{"kind": "k1"}, {"name": "k2"}], ["k1", "k2"])):
            with mock.patch.object(web_steward, "http_jobs", lambda sid, **k: {"ok": True, "kinds": body}):
                self.assertEqual(web_steward._job_kinds_list("default"), want)
        with mock.patch.object(web_steward, "http_jobs", lambda sid, **k: {"ok": False}):
            self.assertEqual(web_steward._job_kinds_list("default"), [])

    def test_brain_answer_after_submit_ok(self):
        q = self._job_q()
        sj.save_record(sj.new_record("varaka", 42, "mkt", "embed", "queued", "k1", now=q.created_at + 30))
        self.assertTrue(web_steward.http_answer({"id": q.id, "answer": "iş #42 queued", "actor": "brain"})["ok"])


class SkipMemoryHttpTest(HttpTest):
    def test_skip_records_signature_from_last_tour(self):
        sw.save_state({"tour_sig": {"p1": "abc123"}})
        self.assertTrue(web_steward.http_skip({"name": "p1", "reason": "x"})["ok"])
        rec = sw.load_state()["skip_seen"]["p1"]
        self.assertEqual(rec["sig"], "abc123")
        web_steward.http_skip({"name": "zz", "reason": "x"})            # turda olmayan ad: kayıt yok
        self.assertNotIn("zz", sw.load_state()["skip_seen"])

    def test_close_stale_answer_action_marks_delivered(self):
        q, _ = sw.add_question_ex("cli20261021", "?", source="brain")
        sw.answer_question(q.id, "a")
        res = web_steward._apply(sw.Action("close_stale_answer", "cli20261021", "bayat", {"question_id": q.id}), sw.Config(), {})
        self.assertTrue(res["ok"])
        self.assertEqual(sw.undelivered_answers(), [])


class ActionJournalTest(HttpTest):
    """codex R-2: işaret tüketilip eylem çökmeyle kaybolmasın ('bekliyor' -> 'tamamlandı'); yeniden denemede çift eylem yok."""

    def _env(self):
        self._observe_env("act")
        sw.upsert_project("a", phase="planned", cadence_minutes=0)

    def test_crash_between_state_save_and_apply_replays_once(self):
        self._env()
        v = _view("a", last_assistant="STEWARD-ASK: A mı B mi?\nSTEWARD-IDEA: yeni bir şey")
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: [v]), \
             mock.patch.object(web_steward, "_apply", side_effect=KeyboardInterrupt):      # süreç ölümü: istisna tick'ten kaçar
            with self.assertRaises(KeyboardInterrupt):
                web_steward.tick_once("timer")
        st = sw.load_state()
        self.assertEqual(sorted(e["kind"] for e in st["act_journal"]), ["ask_user", "idea"])      # state'te bekliyor
        self.assertEqual((sw.open_questions(), sw.load_ideas()), ([], []))                         # eylem uygulanmadı
        # yeniden başlatma: aynı yanıt zaten tüketilmiş (seen_assistant), yine de eylemler tek kez uygulanır
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: [v]):
            web_steward.tick_once("timer")
            web_steward.tick_once("timer")
        self.assertEqual(len(sw.open_questions()), 1)
        self.assertEqual(len(sw.load_ideas()), 1)
        self.assertNotIn("act_journal", sw.load_state())                                          # tamamlandı: girdi yok

    def test_normal_tick_leaves_no_journal_and_no_duplicates(self):
        self._env()
        v = _view("a", last_assistant="STEWARD-ASK: A mı B mi?\nSTEWARD-IDEA: yeni bir şey")
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: [v]):
            for _ in range(3):
                web_steward.tick_once("timer")
        self.assertNotIn("act_journal", sw.load_state())
        self.assertEqual((len(sw.open_questions()), len(sw.load_ideas())), (1, 1))

    def test_replay_skips_duplicate_idea(self):
        self._env()
        sw.add_idea("aynı fikir", source="a")
        st = sw.load_state()
        a = sw.Action("idea", "a", "STEWARD-IDEA", {"text": "aynı fikir"})
        st["act_journal"] = web_steward._journal_entries([a], 1.0)
        sw.save_state(st)
        with mock.patch.object(web_steward, "_collect_views", lambda cfg: []):
            web_steward.tick_once("timer")
        self.assertEqual(len(sw.load_ideas()), 1)
        self.assertNotIn("act_journal", sw.load_state())


class DryReportTest(HttpTest):
    """TBD#138 a: `would:*` dökümü ve 72 saat sonra TEK "act?" sorusu (kip başına bir kez)."""

    def _log(self, paths, event, hours_ago, name="s1", chars=100):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - hours_ago * 3600))
        os.makedirs(os.path.dirname(sw._pp(paths).log), exist_ok=True)
        with open(sw._pp(paths).log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ts, "event": event, "name": name, "chars": chars}) + "\n")

    def test_report_counts_and_window(self):
        paths = sw.paths_for("default")
        self._log(paths, "would:wake_repeat", 80)          # pencere dışı
        self._log(paths, "would:wake_repeat", 10)
        self._log(paths, "would:wake_repeat", 5, name="s2")
        self._log(paths, "tick", 1)
        rep = sw.dry_report(paths)
        self.assertEqual(rep["wake_repeat"]["count"], 2)
        self.assertEqual(rep["wake_repeat"]["chars"], 200)
        self.assertEqual(set(rep["wake_repeat"]["names"]), {"s1", "s2"})
        self.assertIn("would:wake_repeat [wake_gate]: 2 olay", sw.dry_report_text(rep))

    def test_ask_due_only_known_kip_after_72h_once(self):
        paths = sw.paths_for("default")
        self._log(paths, "would:keepwarm", 71)
        self._log(paths, "would:wake_cap", 71.5)
        self._log(paths, "would:handover", 1)               # gözlem kipi eylemi: kip değil
        rep = sw.dry_report(paths, hours=100)
        now = time.time()
        self.assertEqual(sw.dry_ask_due(rep, [], now), [])                    # 72 saat dolmadı
        self.assertEqual(sw.dry_ask_due(rep, [], now + 3600), ["keepwarm", "wake_gate"])
        self.assertEqual(sw.dry_ask_due(rep, ["wake_gate"], now + 3600), ["keepwarm"])

    def test_maybe_dry_ask_opens_one_question_and_not_again(self):
        paths = sw.paths_for("default")
        self._log(paths, "would:wake_cap", 80)
        cfg = _cfg(wake_gate="dry")
        with mock.patch.object(web_steward, "_notify", lambda *a, **k: True):
            qid = web_steward.maybe_dry_ask(cfg, time.time())
            self.assertTrue(qid)
            self.assertIsNone(web_steward.maybe_dry_ask(cfg, time.time()))
        self.assertEqual(len([q for q in sw.open_questions() if q.source == "dry-report"]), 1)

    def test_no_ask_when_kip_already_act(self):
        paths = sw.paths_for("default")
        self._log(paths, "would:wake_cap", 80)
        with mock.patch.object(web_steward, "_notify", lambda *a, **k: True):
            self.assertIsNone(web_steward.maybe_dry_ask(_cfg(wake_gate="act"), time.time()))


class BrainWakeGateTest(HttpTest):
    """TBD#138 b: beyin direktifi (reason=brain, actor=brain, cevapsız) de kapıya girer; günlük üst sınır AYRI sayaçta."""

    def test_brain_directive_capped_per_day_separately_from_due(self):
        cfg = _cfg(wake_gate="act", wake_repeat_minutes=0, brain_wake_max_per_day=2, wake_max_per_day=2)
        paths = sw.paths_for("default")
        for i in range(2):
            self.assertFalse(web_steward._wake_gate(cfg, paths, "s1", "brain", None, f"b{i}", "brain"))
            web_steward._wake_record(cfg, paths, "s1", "brain", None, f"b{i}", "brain")
        self.assertTrue(web_steward._wake_gate(cfg, paths, "s1", "brain", None, "b3", "brain"))      # 3.sü gitmez
        self.assertFalse(web_steward._wake_gate(cfg, paths, "s1", "due", None, "d0"))                 # `due` sayacı ayrı
        self.assertFalse(web_steward._wake_gate(cfg, paths, "s1", "brain", None, "b3", ""))           # actor brain değil: kapı dışı
        web_steward._wake_record(cfg, paths, "s1", "answer", None, "x")                               # cevap = yeni girdi: sıfırlanır
        self.assertFalse(web_steward._wake_gate(cfg, paths, "s1", "brain", None, "b4", "brain"))

    def test_brain_gate_dry_logs_would_and_sends(self):
        cfg = _cfg(wake_gate="dry", wake_repeat_minutes=0, brain_wake_max_per_day=1)
        paths = sw.paths_for("default")
        web_steward._wake_record(cfg, paths, "s1", "brain", None, "b0", "brain")
        self.assertFalse(web_steward._wake_gate(cfg, paths, "s1", "brain", None, "b1", "brain"))
        self.assertTrue(any(e.get("event") == "would:brain_wake_cap" for e in sw.read_log(paths=paths)) if hasattr(sw, "read_log") else True)


class WakeGateTest(HttpTest):
    """TBD#121: aynı metinli otomatik `due` uyandırması pencerede tekrar gitmez (önce dry ölçüm, sonra act)."""

    def _gate(self, mode, reason="due", answer=None, msg="Plan hazır", sname="s1", minutes=240):
        cfg = _cfg(wake_gate=mode, wake_repeat_minutes=minutes)
        paths = sw.paths_for("default")
        return web_steward._wake_gate(cfg, paths, sname, reason, answer, msg), cfg, paths

    def test_first_send_never_gated_then_repeat_dry_logs_but_sends_act_skips(self):
        for mode, skipped in (("dry", False), ("act", True)):
            sw.save_state({})
            gated, cfg, paths = self._gate(mode)
            self.assertFalse(gated)
            web_steward._wake_record(cfg, paths, "s1", "due", None, "Plan hazır")
            gated, _c, _p = self._gate(mode)
            self.assertEqual(gated, skipped, mode)
            evs = [e["event"] for e in sw.tail_log(20)]
            self.assertIn("would:wake_repeat" if mode == "dry" else "wake_repeat_skipped", evs)

    def test_gate_is_skipped_when_the_directive_just_opened_the_session(self):
        # TODO 2026-10-28 (21): kapı oturum AÇILDIKTAN sonra değerlendiriliyordu: act'te oturum açılır ama yönerge gitmezdi
        sw.save_state({})
        proj = sw.Project(name="s1", phase="planned")
        cfg = _cfg(wake_gate="act", wake_repeat_minutes=240)
        paths = sw.paths_for("default")
        msg = sw.build_directive(proj, lang=cfg.lang, extra="", answer=None, more=None, compact=False, paths=paths)
        web_steward._wake_record(cfg, paths, "s1", "due", None, msg)          # ESKİ yaşamdan kalan aynı metin kaydı
        sess = mock.Mock(pid=1, cli="claude")
        sess.name = "s1"
        sent = []
        for opened in (False, True):
            sent.clear()
            lives = [[sess]] if not opened else [[], [sess]]
            with mock.patch.object(web_steward, "_live_sessions", side_effect=lambda *a, _l=lives, **k: _l.pop(0) if len(_l) > 1 else _l[0]), \
                    mock.patch.object(web_steward, "_ensure_running", lambda *a, **k: {"ok": True, "started": True}), \
                    mock.patch.object(web_steward, "is_tmux_backed", lambda pid: True), \
                    mock.patch.object(web_steward, "_proc_born", lambda pid: 0.0), \
                    mock.patch.object(web_steward, "_send", lambda n, c, m, **k: sent.append(n) or True):
                r = web_steward._give_directive(proj, "", reason="due", cfg=cfg, host="")
            self.assertEqual(bool(sent), opened, (opened, r))                    # çalışana tekrar gitmez, AÇILANA gider

    def test_other_text_other_reason_answer_off_and_window(self):
        sw.save_state({})
        gated, cfg, paths = self._gate("act")
        web_steward._wake_record(cfg, paths, "s1", "due", None, "Plan hazır")
        self.assertFalse(self._gate("act", msg="başka metin")[0])
        self.assertFalse(self._gate("act", reason="answer")[0])
        self.assertFalse(self._gate("act", answer=object())[0])
        self.assertFalse(self._gate("off")[0])
        self.assertFalse(self._gate("act", minutes=0)[0])
        self.assertFalse(self._gate("act", sname="s2")[0])
        st = sw.load_state()
        st["wake_sent"]["s1"]["at"] -= 241 * 60
        sw.save_state(st)
        self.assertFalse(self._gate("act")[0])                                  # pencere doldu: yeniden gider
        web_steward._wake_record(cfg, paths, "s1", "answer", None, "x")        # kapı dışı neden kaydı değiştirmez
        self.assertNotEqual(sw.load_state()["wake_sent"]["s1"]["at"], 0)


class BigResumeTest(HttpTest):
    """TBD#123: durmuş oturum büyük bağlamlı konuşmayı --resume etmesin, taze açılsın."""

    def _patch(self, tokens, cli="claude", cwd="/x"):
        prov = mock.Mock()
        prov.resolve_resume_id.return_value = "sid1" if tokens is not None else None
        return [mock.patch.object(web_steward, "_cwd_resolver", lambda: (lambda n: cwd)),
                mock.patch.object(web_steward, "_project_cli", lambda n: cli),
                mock.patch.object(web_steward, "get_provider", lambda c: prov),
                mock.patch.object(web_steward, "context_tokens_for", lambda c, i: tokens)]

    def _run(self, patches, fn):
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return fn()

    def test_oversized_detection(self):
        cfg = _cfg(resume_max_context_tokens=150000)
        self.assertEqual(self._run(self._patch(386000), lambda: web_steward._oversized_resume("ysf", cfg)), 386000)

    def test_small_unknown_other_cli_and_off_keep_resume(self):
        cfg = _cfg(resume_max_context_tokens=150000)
        for tokens, c, conf in ((100000, "claude", cfg), (None, "claude", cfg), (386000, "agy", cfg),
                                (386000, "claude", _cfg(resume_max_context_tokens=0))):
            for p in self._patch(tokens, cli=c):
                p.start()
            try:
                self.assertEqual(web_steward._oversized_resume("ysf", conf), 0, (tokens, c))
            finally:
                mock.patch.stopall()

    def test_ensure_running_starts_fresh_for_big_context(self):
        seen = {}
        cfg = _cfg(resume_max_context_tokens=150000)
        web_steward.configure(start=lambda name, model="", effort="", fresh=False, lang="tr": seen.update(fresh=fresh) or {"ok": True})
        patches = self._patch(386000) + [mock.patch.object(web_steward, "steward_config", lambda sid="default": cfg),
                                         mock.patch.object(web_steward, "_live_sessions", lambda n, s: []),
                                         mock.patch.object(web_steward, "_wait_ready", lambda n, c: True),
                                         mock.patch.object(web_steward, "_launch_kwargs", lambda n, m, e: {}),
                                         mock.patch.object(web_steward, "_start_appeared", lambda n, s="default": True),
                                         mock.patch.object(web_steward, "_verify_brain_mcp", lambda c, since: True)]
        self._run(patches, lambda: web_steward._ensure_running("ysf"))
        self.assertTrue(seen["fresh"])
        self.assertTrue(any(e["event"] == "start_fresh_big_context" for e in sw.tail_log(20)))


class WakeCapPanicTest(HttpTest):
    def test_daily_cap_dry_and_act_and_reset_on_answer(self):
        paths = sw.paths_for("default")
        sw.save_state({})
        cfg = _cfg(wake_gate="act", wake_repeat_minutes=0, wake_max_per_day=2)
        for i in range(2):
            self.assertFalse(web_steward._wake_gate(cfg, paths, "s1", "due", None, f"m{i}"))
            web_steward._wake_record(cfg, paths, "s1", "due", None, f"m{i}")
        self.assertTrue(web_steward._wake_gate(cfg, paths, "s1", "due", None, "m3"))               # 3.sü gitmez
        self.assertFalse(web_steward._wake_gate(cfg, paths, "s2", "due", None, "m3"))              # başka oturum
        self.assertFalse(web_steward._wake_gate(dataclasses.replace(cfg, wake_gate="dry"), paths, "s1", "due", None, "m3"))
        self.assertTrue(any(e["event"] == "would:wake_cap" for e in sw.tail_log(30)))
        web_steward._wake_record(cfg, paths, "s1", "answer", None, "x")                            # cevap = yeni girdi
        self.assertFalse(web_steward._wake_gate(cfg, paths, "s1", "due", None, "m3"))
        st = sw.load_state()
        st["auto_wake"]["s1"] = [t - 90000 for t in (st.get("auto_wake") or {}).get("s1", [1.0, 2.0])]
        sw.save_state(st)

    def test_panic_flag_forces_observe_and_blocks_brain_directive(self):
        self.assertFalse(sw.panic_active())
        self.assertTrue(web_steward.http_panic({"on": True, "reason": "test"})["panic"])
        try:
            self.assertTrue(sw.panic_active())
            self.assertFalse(web_steward.http_panic({"on": False, "actor": "brain"})["ok"])          # beyin kaldıramaz
            self.assertTrue(sw.panic_active())
            r = web_steward.http_directive({"name": "a", "text": "x", "actor": "brain"})
            self.assertEqual(r.get("code"), "draining")
            self._observe_env("act")
            sw.upsert_project("a", phase="planned", cadence_minutes=60)
            with mock.patch.object(web_steward, "_collect_views", lambda cfg: [_view("a", running=False)]):
                r = web_steward.tick_once("timer")
            self.assertEqual(r["mode"], "observe")
            self.assertEqual(self.touched, [])                                                   # oturuma dokunulmadı
        finally:
            web_steward.http_panic({"on": False})
        self.assertFalse(sw.panic_active())


class BlockedEscalationTest(HttpTest):
    """TBD#140 A: BLOCKED beyinde 4 saat kalır; sahip kararı çıkan rutin madde ANINDA sahibe düşer; metinler tek kaynaktan."""

    def _escalations(self, text, age_s):
        now = 1_000_000.0
        brain = _view("degnekci", busy=True)
        q = [sw.Question(id="q1", project="p", text=text, created_at=now - age_s, routine=True)]
        acts, _ = sw.plan_tick([brain], {"p": sw.Project(name="p", phase="planned")}, {}, _cfg(), now, q, [])
        return [a for a in acts if a.kind == "escalate_routine"]

    def test_blocked_waits_four_hours_routine_thirty_minutes(self):
        blocked = sw.BLOCKED_TEXT_PREFIX + "PDF yok"
        self.assertEqual(self._escalations(blocked, 40 * 60), [])
        self.assertEqual(len(self._escalations(blocked, 5 * 3600)), 1)
        self.assertEqual(len(self._escalations("nasıl açalım?", 40 * 60)), 1)       # düz rutin: eski 30 dk
        self.assertEqual(self._escalations("nasıl açalım?", 10 * 60), [])

    def test_owner_only_denial_escalates_routine_immediately(self):
        q = sw.add_question("p", "main'e force-push yapayım mı?", source="p20261029", routine=True)
        with mock.patch.object(web_steward, "_notify", lambda *a, **k: True):
            r = web_steward.http_answer({"id": q.id, "answer": "evet", "actor": "brain"})
        self.assertEqual(r["code"], "owner_only")
        self.assertFalse(sw.find_question(q.id).routine)                  # sahibe düştü: artık rutin değil
        self.assertEqual(sw.find_question(q.id).status, "open")

    def test_owner_only_denial_blocks_brain_directive_until_answered(self):
        # 7 Kas 2026: red -> 7-17 sn sonra aynı projeye beyin direktifi (owner_only dolanması)
        sw.upsert_project("p", cwd="/w/p")
        q = sw.add_question("p", "main'e force-push yapayım mı?", source="p20261029", routine=True)
        sent = []
        with mock.patch.object(web_steward, "_notify", lambda *a, **k: True), \
                mock.patch.object(web_steward, "_gate", lambda *a, **k: None), \
                mock.patch.object(web_steward, "_brain_directive_defer", lambda *a, **k: ""), \
                mock.patch.object(web_steward, "_give_directive", lambda p, text, **k: sent.append((p.name, text)) or {"ok": True}):
            self.assertEqual(web_steward.http_answer({"id": q.id, "answer": "evet", "actor": "brain"})["code"], "owner_only")
            for target in ("p", "p20261029"):
                r = web_steward.http_directive({"name": target, "text": "force-push yap", "actor": "brain"})
                self.assertEqual(r.get("code"), "owner_pending", target)
            self.assertEqual(sent, [])
            self.assertTrue(web_steward.http_directive({"name": "p", "text": "insan", "actor": "human"})["ok"])   # insan engellenmez
            sw.answer_question(q.id, "hayır")                               # sahip cevapladı: engel kalkar
            self.assertTrue(web_steward.http_directive({"name": "p", "text": "devam", "actor": "brain"})["ok"])
        self.assertEqual([t for _, t in sent], ["insan", "devam"])

    def test_owner_pending_block_pure(self):
        qs = [sw.Question(id="a", project="p", source="p1", text="x", created_at=1.0), sw.Question(id="b", project="r", text="y", created_at=1.0, status="answered")]
        self.assertEqual(sw.owner_pending_block({"p"}, qs, {"a": 1.0}).id, "a")
        self.assertEqual(sw.owner_pending_block({"p1", ""}, qs, {"a": 1.0}).id, "a")
        self.assertIsNone(sw.owner_pending_block({"p"}, qs, {}))           # reddedilmemiş soru engellemez
        self.assertIsNone(sw.owner_pending_block({"r"}, qs, {"b": 1.0}))   # cevaplanmış soru engellemez

    def test_protocol_and_guide_derive_from_owner_topics(self):
        self.assertIn(sw.OWNER_ONLY_TOPICS_TR, sw._PROTOCOL_TR.replace("Force-push", "force-push", 1))
        self.assertNotIn("bana düşmez", sw._PROTOCOL_TR)
        self.assertNotIn("telif, harcama, commit/push", sw.build_workspace_claude_md("P", lang="tr"))


if __name__ == "__main__":
    unittest.main()

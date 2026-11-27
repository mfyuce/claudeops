"""Değnekçi testleri (test_steward.py bölünmüş parça: c). Çalıştırma: python3 -m pytest py/tests/test_steward_core_b.py"""
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
        v = _view("p1", last_assistant="STEWARD-ASK: Hangi yol?\nSTEWARD-IDEA: yeni\nSTEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, kanıt\nSTEWARD-PLAN-READY")
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
        open(sw.LOG_JSONL, "a").close()
        with mock.patch.object(sw, "log_entries_for_date", wraps=sw.log_entries_for_date) as scan:
            sw.missed_summary_dates(now)
            first = scan.call_count
            sw.missed_summary_dates(now)                                       # günlük değişmedi: kayıtsız günler yeniden taranmaz
            self.assertEqual(scan.call_count, first)
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
        with mock.patch("claudeops.providers.claude_provider.jsonl_path_for", lambda cwd, sid: Path(path)):
            self.assertEqual(web_steward.context_tokens_for("/x", "sid"), 400205)
        with mock.patch("claudeops.providers.claude_provider.jsonl_path_for", lambda cwd, sid: None):
            self.assertIsNone(web_steward.context_tokens_for("/x", "sid"))
        # sid bilinmiyorsa mtime tahmini YOK: başka konuşmanın transkripti sahte eşik aşımı üretmişti
        with mock.patch("claudeops.providers.claude_provider.jsonl_path_for", lambda cwd, sid: Path(path)):
            self.assertIsNone(web_steward.context_tokens_for("/x", None))


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
        q2 = next(x for x in sw.load_questions() if x.id == q.id)
        self.assertEqual(q2.undeliverable, "send failed")            # 'iletildi' görünmez: neden kayıtlı
        self.assertTrue(q2.delivered_at)                             # yalnız yeniden deneme durur


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

    def test_answered_routine_question_asked_to_owner_opens_new(self):
        r, _ = sw.add_question_ex("cli", "ncs koşu kayıtlarının yolu reviews/ncs/evren altında mı?", routine=True)
        sw.answer_question(r.id, "evet")
        q, how = sw.add_question_ex("cli", "ncs koşu kayıtlarının yolu reviews/ncs/evren altında mı?")
        self.assertEqual(how, "new")
        self.assertNotEqual(q.id, r.id)
        self.assertFalse(q.routine)
        q2, how2 = sw.add_question_ex("cli", "ncs koşu kayıtlarının yolu reviews/ncs/evren altında mı?", routine=True)
        self.assertNotEqual(how2, "new")      # rutin yeniden soru hâlâ eski yoldan bastırılır / birleşir

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


class JobMarkerParseTest(unittest.TestCase):
    def test_hyphenated_kind_and_malformed_body_are_not_dropped(self):
        m = sw.scan_markers("özet\nSTEWARD-JOB: varaka-import /a/b.md A1 İşârâtü'l-İ'câz importu")
        self.assertEqual(m["jobs"], ["varaka-import /a/b.md A1 İşârâtü'l-İ'câz importu"])
        self.assertEqual(sw.scan_markers("- `STEWARD-JOB: Embed /a.md`")["jobs"], ["Embed /a.md"])
        self.assertEqual(sw.scan_markers("STEWARD-JOB: embed")["jobs"], ["embed"])      # gövde kısa da sessizce düşmez

    def test_prose_mentions_and_placeholders_still_ignored(self):
        for t in ("istek için STEWARD-JOB: embed /a.md yazdım", "`STEWARD-JOB: <iş türü> <dosya yolu>` biçimi", "```\nSTEWARD-JOB: embed /a.md\n```"):
            self.assertEqual(sw.scan_markers(t)["jobs"], [], t)


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

    def test_routine_owner_only_topics(self):
        # sahipte KALAN: force-push, kurulum (apt/sudo/install), silme, harcama, parola/token/yetki
        for t in ("main'e force-push yapayım mı?", "install-ucli.sh çalıştırayım mı?", "sudo apt install tmux yapayım mı?",
                  "dosyayı sileyim mi? delete", "100 dolar harcayayım mı?", "parolayı döndüreyim mi?", "token yenileyeyim mi?"):
            q = sw.Question(id="q2", project="cli", text=t, created_at=0.0, routine=True)
            self.assertFalse(sw.brain_may_answer(q)[0], t)

    def test_commit_push_merge_build_deploy_are_not_owner_only(self):
        # sahip kararı 2026-10-27 (kalıcı izin): commit/push/merge/build/deploy sorulmaz; rutin ise beyin cevaplar
        for t in ("E4/E5 için commit + push yapayım mı?", "ff-only merge edip iki remote'a push edeyim mi?",
                  "dist build edip deploy edeyim mi?"):
            q = sw.Question(id="q2", project="cli", text=t, created_at=0.0, routine=True)
            self.assertEqual(sw.brain_may_answer(q), (True, ""), t)

    def test_blocked_marker_goes_to_brain_not_owner(self):
        acts = sw.marker_record_actions("s", "p", {"asks": [], "routines": [], "blocked": ["PDF yok"], "ideas": []})
        self.assertEqual(len(acts), 1)
        self.assertTrue(acts[0].payload.get("routine"), "genel 'Takıldım' bildirimi sahibe soru olarak düşmemeli")

    def test_rules_text_no_longer_reserves_commit_push_for_owner(self):
        for txt in (sw.GENERIC_RULE_TR, sw.GENERIC_RULE_EN, sw.MODEL_RULE_TR, sw.MODEL_RULE_EN):
            self.assertNotIn("commit, push, merge, deploy", txt.lower().replace("commit/push/merge/deploy", "commit, push, merge, deploy"))
            self.assertNotIn("Commit/push/merge/deploy", txt)

    def test_readonly_job_request_not_owner_only(self):
        # ysf 12 Kas: salt okunur SELECT açıklamasındaki "silinerek" sahibe yanlış yükseltme yapıyordu
        txt = sw.JOB_REQUEST_PREFIX + "sql_readonly data/q.sql ünlü işaretleri SQL'de silinerek aranır"
        q = sw.Question(id="q4", project="ysf", text=txt, created_at=0.0, routine=True)
        self.assertEqual(sw.brain_may_answer(q), (True, ""))
        for kind in ("import_script", "embed"):     # yazan türler eski kapıda kalır
            q = sw.Question(id="q5", project="ysf", text=sw.JOB_REQUEST_PREFIX + kind + " x.py eski kayıtları sil", created_at=0.0, routine=True)
            self.assertFalse(sw.brain_may_answer(q)[0], kind)
        q = sw.Question(id="q6", project="ysf", text="sql_readonly ile tabloyu sileyim mi?", created_at=0.0, routine=True)
        self.assertFalse(sw.brain_may_answer(q)[0])

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


class ShutdownOnlyTest(unittest.TestCase):
    """`shutdown --only P`: yalnız P'nin oturumu devir alıp durur; diğer proje ve beyin dokunulmaz, kapatma beyin adımı yok."""

    def test_only_closes_selected_project_and_leaves_rest(self):
        projects = {"ncs": sw.Project(name="ncs"), "vc": sw.Project(name="vc")}
        brain = _view("degnekci", last_activity=100.0)
        ncs = _view("ncs", last_activity=100.0)
        vc = _view("vc", last_activity=100.0)
        acts, sd, done = sw.plan_shutdown([brain, ncs, vc], projects, {"only": ["ncs"]}, _cfg(), 1000.0)
        self.assertEqual([(a.kind, a.name) for a in acts], [("handover", "ncs")])
        self.assertNotIn("vc", sd["items"])
        ncs2 = _view("ncs", last_activity=1500.0, last_assistant=sw.READY_FOR_HANDOVER)
        acts, sd, done = sw.plan_shutdown([brain, ncs2, vc], projects, sd, _cfg(), 1600.0)
        self.assertEqual([(a.kind, a.name) for a in acts], [("stop", "ncs")])
        self.assertNotIn("degnekci", sd["items"])
        self.assertTrue(done)


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


class SmartTickTest(unittest.TestCase):
    """Akıllı tick: acil madde tur aralığını beklemez; done kuralı TBD'ye de bakar; yalnız-TBD proje açılmaz (sahibe soru);
    açık TODO'su olmayan boşta oturum dürtülmez."""
    now = 100000.0

    def test_count_open_tbd(self):
        t = "# x\n## Açık\n### 5) **AÇIK a**\n### 4) ~~kapalı~~\n### 3) **KARAR 2026 x**\n### 2) **AÇIK b**\n## Kapalı\n### 1) **AÇIK eski**\n"
        self.assertEqual(sw.count_open_tbd(t), 2)
        self.assertEqual(sw.count_open_tbd(""), 0)

    def test_routine_question_skips_tour_interval(self):
        cfg = _cfg(tour_minutes=15)
        brain = _view("degnekci", busy=False)
        q = [sw.Question(id="q1", project="p", text="nasıl?", created_at=self.now - 30, routine=True)]
        projects = {"p": sw.Project(name="p", phase="planned")}
        acts, _ = sw.plan_tick([brain], projects, {"last_tour": self.now - 120}, cfg, self.now, q, [])
        self.assertEqual([a.kind for a in acts if a.kind == "tour"], ["tour"])
        # son turdan ESKİ rutin soru acil değil: tur aralığı beklenir (cevaplanamayan soru her tick tur yakmasın)
        q[0].created_at = self.now - 600
        acts, _ = sw.plan_tick([brain], projects, {"last_tour": self.now - 120}, cfg, self.now, q, [])
        self.assertEqual([a.kind for a in acts if a.kind == "tour"], [])
        ideas = [sw.Idea(id="i", text="t", created_at=0)]
        acts, _ = sw.plan_tick([brain], projects, {"last_tour": self.now - 120}, cfg, self.now, [], ideas)
        self.assertEqual([a.kind for a in acts if a.kind == "tour"], [])    # acil değil: aralık beklenir

    def test_done_confirmed_with_open_tbd_asks_owner(self):
        ok = "bitti\nSTEWARD-DONE-CONFIRMED: abc1234 kalan açık iş 0, testler yeşil"
        projects = {"p1": sw.Project(name="p1", phase="planned")}
        acts, _ = sw.plan_tick([_view("p1", last_assistant=ok)], projects, {"done_confirm": {"p1": self.now - 100}}, _cfg(), self.now, [], [],
                               open_work=lambda p: 0, open_tbd=lambda p: 2)
        # açık sahip sorusu varken done DEĞİL paused (sahip bekliyor) + oturum kapanır (17 Kas, marwan)
        self.assertEqual([(a.kind, (a.payload or {}).get("phase")) for a in acts if a.kind in ("set_phase", "stop", "ask_user")],
                         [("ask_user", None), ("set_phase", "paused"), ("stop", None)])
        acts, _ = sw.plan_tick([_view("p1", last_assistant=ok)], projects, {"done_confirm": {"p1": self.now - 100}}, _cfg(), self.now, [], [],
                               open_work=lambda p: 0, open_tbd=lambda p: 0)
        self.assertEqual([a.kind for a in acts if a.kind in ("set_phase", "stop")], ["set_phase", "stop"])

    def test_tbd_only_question_counts_once(self):
        projects = {"p": sw.Project(name="p", phase="planned", cadence_minutes=5)}
        reads = []      # ikinci okuma başarısız (None): metne "None açık karar" yazılmamalı

        def open_work(_p):
            reads.clear()
            return 0

        def open_tbd(_p):
            reads.append(1)
            return 3 if len(reads) == 1 else None
        acts, _ = sw.plan_tick([], projects, {}, _cfg(), self.now, [], [], open_work=open_work, open_tbd=open_tbd)
        self.assertIn("3 açık karar", [a for a in acts if a.kind == "ask_user"][0].payload["text"])

    def test_tbd_only_project_not_started_owner_asked_once(self):
        projects = {"p": sw.Project(name="p", phase="planned", cadence_minutes=5)}
        kw = dict(open_work=lambda p: 0, open_tbd=lambda p: 3)
        acts, st = sw.plan_tick([], projects, {}, _cfg(), self.now, [], [], **kw)
        self.assertEqual([a.kind for a in acts if a.kind in ("start", "ask_user")], ["ask_user"])
        acts, st = sw.plan_tick([], projects, st, _cfg(), self.now + 300, [], [], **kw)
        self.assertEqual([a.kind for a in acts if a.kind in ("start", "ask_user")], [])     # 6 saat dolmadan tekrar sormaz, açmaz
        acts, _ = sw.plan_tick([], projects, {}, _cfg(), self.now, [], [], open_work=lambda p: 2, open_tbd=lambda p: 3)
        self.assertEqual([a.kind for a in acts if a.kind == "start"], ["start"])           # TODO'su varsa açılır

    def test_brain_stopped_project_not_restarted_by_cadence_until_cooldown(self):
        projects = {"p": sw.Project(name="p", phase="planned", cadence_minutes=5)}
        st = {"brain_stopped": {"p20261030": self.now - 60}}       # tarihli oturum adı proje adına çözülür
        acts, _ = sw.plan_tick([], projects, dict(st), _cfg(), self.now, [], [], open_work=lambda p: 2, open_tbd=lambda p: 0)
        self.assertEqual([a.kind for a in acts if a.kind == "start"], [])
        acts, _ = sw.plan_tick([], projects, dict(st), _cfg(), self.now + sw.BRAIN_STOP_COOLDOWN_SECONDS + 1, [], [],
                               open_work=lambda p: 2, open_tbd=lambda p: 0)
        self.assertEqual([a.kind for a in acts if a.kind == "start"], ["start"])           # soğuma bitti: açılır
        other = {"pp": sw.Project(name="pp", phase="planned", cadence_minutes=5)}
        acts, _ = sw.plan_tick([], other, dict(st), _cfg(), self.now, [], [], open_work=lambda p: 2, open_tbd=lambda p: 0)
        self.assertEqual([a.kind for a in acts if a.kind == "start"], ["start"])           # başka proje etkilenmez

    def test_idle_session_without_open_todo_not_nudged(self):
        cfg = _cfg(idle_minutes=5)
        projects = {"a": sw.Project(name="a", phase="planned")}
        idle = _view("a", busy=False, last_activity=self.now - 600)
        items = sw.review_items([idle], projects, cfg, self.now, [], [], open_work=lambda p: 0)
        self.assertEqual([i for i in items if i["kind"] == "idle"], [])
        items = sw.review_items([idle], projects, cfg, self.now, [], [], open_work=lambda p: 3)
        self.assertEqual([i["kind"] for i in items], ["idle"])
        items = sw.review_items([idle], projects, cfg, self.now, [], [], open_work=lambda p: None)
        self.assertEqual([i["kind"] for i in items], ["idle"])      # bilinmiyor: eski davranış


class AskStatusLineTests(unittest.TestCase):
    def test_status_lines_do_not_open_records(self):
        for q in ("Yok", "Hayır, sormuyorum.", "soru yok", "Takıldım: yok"[:0] or "yeni soru yok"):
            self.assertTrue(sw._ask_is_status_line(q), q)
            self.assertEqual(sw.marker_record_actions("a", "p", {"asks": [q], "routines": [], "blocked": [], "ideas": []}), [])
        for q in ("Hayır mı evet mi?", "A mı B mi yapayım, öneri A", "hangi dalı kullanayım",
                  "Yok saymak için şu dosyayı silmemi onaylar mısın? " + "x" * 80):
            self.assertFalse(sw._ask_is_status_line(q), q)


class AskBaseTests(unittest.TestCase):
    def test_dated_session_name_collapses_to_base(self):
        for n, b in (("mecdtfl20261031_3", "mecdtfl"), ("ncs20261011_6", "ncs"), ("cops20260930_1", "cops"),
                     ("hc", "hc"), ("danisppr", "danisppr"), ("hc58_2", "hc")):
            self.assertEqual(sw._ask_base(n), b, n)
        acts = sw.marker_record_actions("mecdtfl20261031_3", "", {"asks": ["Hangisi, A mı B mi?"], "routines": [], "blocked": [], "ideas": []})
        self.assertEqual(acts[0].payload["project"], "mecdtfl")
        acts = sw.marker_record_actions("x20261031_3", "reg", {"asks": ["A mı B mi?"], "routines": [], "blocked": [], "ideas": []})
        self.assertEqual(acts[0].payload["project"], "reg")


class DeferAnswerTests(unittest.TestCase):
    def test_is_defer_answer(self):
        for a in ("Sonra", "kararları şimdi vereceğim", "TBD", "later."):
            self.assertTrue(sw.is_defer_answer(a), a)
        for a in ("A", "sonra bakarız ama önce X'i sil", "evet"):
            self.assertFalse(sw.is_defer_answer(a), a)

    def test_digest_hides_deferred_until_expiry(self):
        q = sw.Question(id="q1", project="p", text="soru", created_at=0)
        q.deferred_until = 1000.0 + sw.DEFER_SECONDS
        self.assertEqual(sw.pending_digest_text([q], 1000.0), "")
        self.assertIn("1 soru", sw.pending_digest_text([q], q.deferred_until + 1))


class StartDecisionEventTests(unittest.TestCase):
    def test_event_shape(self):
        A = sw.Action
        self.assertEqual(sw.start_decision_event([], {}), {})
        d = sw.start_decision_event([A("start", "b", "due"), A("start", "a", "due"), A("start", "x", "answer → start")], {})
        self.assertEqual(d, {"allowed": ["a", "b"], "blocked": [], "reason": ""})
        st = {"start_blocked": {"projects": ["c"], "reason": "max_active", "active": 3, "max_active": 3}}
        d = sw.start_decision_event([A("start", "a", "due")], st)
        self.assertEqual((d["allowed"], d["blocked"], d["reason"], d["max_active"]), (["a"], ["c"], "max_active", 3))


class ExpiredHandoverNoteTest(unittest.TestCase):
    """D24: READY FOR HANDOVER gelmeden devir süresi dolarsa respawn eylemi eski oturumun son metnini kart notu olarak taşır."""
    def test_note_helper(self):
        self.assertEqual(sw.expired_handover_note("", "tr"), "")
        self.assertIn("son mesajı".lower(), sw.expired_handover_note("x", "tr").lower())
        self.assertIn("last message", sw.expired_handover_note("x", "en"))
        long = sw.expired_handover_note("a " * 3000, "tr")
        self.assertLess(len(long), sw.CARD_NOTE_MAX_CHARS + 200)

    def _plan(self, last, ready):
        cfg = _cfg()
        txt = (last + "\nREADY FOR HANDOVER") if ready else last
        projects = {"p1": sw.Project(name="p1", phase="planned", cadence_minutes=60)}
        acts, _ = sw.plan_tick([_view("p1", last_assistant=txt)], projects, {"ho_pending": {"p1": 1000.0}}, cfg, 1000.0 + cfg.ho_grace_minutes * 60 + 5, [], [])
        return [a for a in acts if a.kind == "respawn"]

    def test_expired_without_marker_carries_note(self):
        rs = self._plan("son durum: X bitti, Y kaldı", ready=False)
        self.assertEqual(len(rs), 1)
        self.assertIn("Y kaldı", rs[0].payload.get("card_note", ""))

    def test_ready_marker_has_no_card_note(self):
        rs = self._plan("özet", ready=True)
        self.assertEqual(len(rs), 1)
        self.assertNotIn("card_note", rs[0].payload)


class UcliStuckLadderTest(unittest.TestCase):
    """D12: ucli kutusu art arda takılırsa 2. takılmadan sonra metin kısalır, 3.'de sahibe bildirim (6 saatte bir); başarı sayacı sıfırlar."""
    def setUp(self):
        from claudeops.commands import web_steward as ws
        self.ws = ws
        ws._UCLI_STUCK.clear(); ws._UCLI_STUCK_NOTIFIED.clear()
        self.addCleanup(ws._UCLI_STUCK.clear); self.addCleanup(ws._UCLI_STUCK_NOTIFIED.clear)

    def test_shorten_helper(self):
        ws = self.ws
        self.assertEqual(ws.ucli_shorten_text("kısa"), "kısa")
        long = ws.ucli_shorten_text("a" * 5000)
        self.assertLess(len(long), ws.UCLI_SHORTEN_CHARS + 200)
        self.assertIn("kısaltıldı", long)

    def test_ladder(self):
        ws = self.ws
        self.assertEqual(ws._ucli_stuck_update("u", True, now=100.0), "")           # 1. takılma: yalnız Enter denendi
        self.assertEqual(ws._ucli_stuck_update("u", True, now=101.0), "shorten")    # 2.: sıradaki gönderim kısalır
        self.assertEqual(ws._ucli_stuck_update("u", True, now=102.0), "ask")        # 3.: sahibe
        self.assertEqual(ws._ucli_stuck_update("u", True, now=103.0), "")           # 6 saat içinde tekrar sorma
        self.assertEqual(ws._ucli_stuck_update("u", False, now=104.0), "")          # başarı: sıfırla
        self.assertEqual(ws._ucli_stuck_update("u", True, now=105.0), "")


class RemoteRespawnNoteTest(unittest.TestCase):
    """D24: uzak respawn da süresi dolmuş devirde eski oturumun son metnini ilk yönergeye ekler; notsuzsa boş yönerge."""
    def _run(self, note):
        from claudeops.commands import web_steward as ws
        seen = {}
        def fake_give(project, text, **kw):
            seen["text"] = text
            return {"ok": True}
        p = sw.Project(name="p1", phase="planned", cadence_minutes=60)
        with mock.patch.object(ws, "_remote_stop_and_wait", lambda *a, **k: None), \
                mock.patch.object(ws, "_main_model_effort", lambda *a, **k: ("", "")), \
                mock.patch.object(ws, "_ensure_running_remote", lambda *a, **k: {"ok": True, "name": "p1x"}), \
                mock.patch.object(ws, "_give_directive", fake_give), \
                mock.patch.object(sw, "log_event", lambda *a, **k: None):
            res = ws._remote_respawn("p1", "h1", p, _cfg(), None, None, note=note)
        return res, seen

    def test_note_reaches_directive(self):
        res, seen = self._run("önceki durum: Y kaldı")
        self.assertTrue(res["ok"])
        self.assertEqual(seen["text"], "önceki durum: Y kaldı")

    def test_no_note_keeps_empty_directive(self):
        _, seen = self._run("")
        self.assertEqual(seen["text"], "")


if __name__ == "__main__":
    unittest.main()

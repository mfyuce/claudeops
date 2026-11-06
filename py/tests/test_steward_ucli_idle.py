"""TBD#156 motor kuralı: yönetilen ucli kodcu 5 dk'dan fazla boşta kalmasın (`sw.plan_ucli_idle` + `web_steward._apply`).

Saf karar testleri sahte görünümlerle; uygulama testleri `_Engine` taban sınıfıyla (gerçek spawn/tmux/ağ YOK, geçici dizin,
gerçek ~/.claude/claudeops dosyalarına dokunulmaz). Çalıştırma: python3 -m unittest discover -s py/tests"""
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402
from test_steward_engine_multi import _Engine  # noqa: E402

NOW = 1_800_000_000.0


def proj(notes="", phase="planned", name="cli"):
    return {name: sw.Project(name=name, phase=phase, notes=notes)}


def view(name="cli", idle=400, **kw):
    base = dict(running=True, cwd="/w", cli="ucli", busy=False, tmux=True, started_at=1.0,
                last_activity=0.0, idle_since=NOW - idle, cache_ttl="5m", last_assistant="")
    base.update(kw)
    return sw.SessionView(name=name, **base)


def cfg(**kw):
    c = sw.Config(enabled=True, mode="act", ucli_idle="act")
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def plan(views, projects=None, state=None, c=None, now=NOW, planned=(), open_work=None):
    return sw.plan_ucli_idle(views, projects if projects is not None else proj("sıradaki: testleri yaz"),
                             state or {}, c or cfg(), now, list(planned), open_work=open_work)


class IdleModeTest(unittest.TestCase):
    def test_off_produces_nothing(self):
        acts, st = plan([view(last_assistant="STEWARD-DONE")], c=cfg(ucli_idle="off"))
        self.assertEqual(acts, [])
        self.assertNotIn("ucli_idle", st)
        self.assertEqual(plan([view()], c=cfg(ucli_idle="off"))[0], [])

    def test_dry_plans_but_never_writes_handover_state(self):
        acts, st = plan([view(last_assistant="STEWARD-DONE")], c=cfg(ucli_idle="dry"))
        self.assertEqual([a.kind for a in acts], ["idle_close"])      # motor bunu would: olarak kaydeder, uygulamaz
        self.assertNotIn("ho_pending", st)
        self.assertNotIn("ho_close", st)
        acts, st = plan([view(last_assistant="yapacak iş yok")], proj(""), c=cfg(ucli_idle="dry"))
        self.assertEqual([a.kind for a in acts], ["idle_close"])
        self.assertNotIn("ho_pending", st)
        self.assertNotIn("ho_close", st)
        acts, _ = plan([view()], c=cfg(ucli_idle="dry"))
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])

    def test_default_config_is_dry(self):
        self.assertEqual(sw.Config().ucli_idle, "dry")


class FailedTurnChainTest(unittest.TestCase):
    ERR = "This turn failed: HTTP 404 model not found"

    def test_detect(self):
        self.assertTrue(sw.turn_failed(self.ERR))
        self.assertTrue(sw.turn_failed("rate limited, wait a minute"))
        self.assertFalse(sw.turn_failed("Testler geçti"))

    def test_failed_turn_does_not_reset_chain(self):
        c = cfg()
        v1 = view(last_assistant=self.ERR, idle=400)
        acts, st = plan([v1], c=c)
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])
        # dürtme sonrası ucli başarısız tur verdi: son etkinlik ilerledi ama zincir SIFIRLANMAZ
        t2 = NOW + 1000
        v2 = view(last_assistant=self.ERR, idle=400, idle_since=t2 - 400)
        acts, st = plan([v2], c=c, state=st, now=t2)
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])
        self.assertEqual(st["ucli_idle"]["cli"]["n"], 2)
        t3 = t2 + 1000
        v3 = view(last_assistant=self.ERR, idle=400, idle_since=t3 - 400)
        acts, st = plan([v3], c=c, state=st, now=t3)       # max_consecutive=2 doldu: dürtme yok, kapat
        self.assertEqual([a.kind for a in acts], ["idle_close"])
        self.assertEqual(acts[0].payload["marker"], "turn_failed")
        self.assertEqual(acts[0].payload["mode"], "stop")
        self.assertTrue(st["ucli_idle"]["cli"]["failed_closed"])
        t4 = t3 + 1000
        v4 = view(last_assistant=self.ERR, idle=400, idle_since=t4 - 400)
        acts, _ = plan([v4], c=c, state=st, now=t4)
        self.assertEqual(acts, [])                          # bir kez kapatılır

    def test_successful_turn_still_resets_chain(self):
        c = cfg()
        acts, st = plan([view(last_assistant="bitirdim, sıradaki yok")], proj("sıradaki: testleri yaz"), c=c)
        t2 = NOW + 1000
        acts, st = plan([view(last_assistant="devam ediyorum", idle=400, idle_since=t2 - 400)], c=c, state=st, now=t2)
        self.assertEqual(st["ucli_idle"]["cli"]["n"], 1)


class GateWaitTest(unittest.TestCase):
    def test_gate_wait_text_detected(self):
        for t in ("Commit hazır, kapı onayı bekliyor.", "Merge için kapıya haber verdim", "kapı bekliyor",
                  "Waiting for the gate to review", "tamam. Kapı onayı bekleniyor"):
            self.assertTrue(sw.waiting_for_gate(t), t)
        for t in ("", "kapıyı kapattım", "iş bitti", "STEWARD-DONE"):
            self.assertFalse(sw.waiting_for_gate(t), t)

    def test_no_nudge_no_close_while_waiting_for_gate(self):
        acts, st = plan([view(last_assistant="Testler geçti, commit hazır. Kapı onayı bekliyor.")])
        self.assertEqual(acts, [])
        self.assertNotIn("ucli_idle", st)
        # bitti işareti de olsa bekle: devir/kapatma yok
        acts, _ = plan([view(last_assistant="STEWARD-DONE\nkapı onayı bekliyor")])
        self.assertEqual(acts, [])

    def test_old_gate_text_far_back_does_not_block(self):
        text = "kapı onayı bekliyor\n" + ("x" * 900) + "\nsıradaki işe geçtim"
        acts, _ = plan([view(last_assistant=text)])
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])


class HelpersTest(unittest.TestCase):
    def test_one_line_folds_newlines(self):
        self.assertEqual(sw.one_line("devam:\n  a\r\n\tb  c"), "devam: a b c")

    def test_threshold_by_cache_ttl(self):
        c = cfg()
        self.assertEqual(sw.ucli_idle_threshold(c, "5m"), 180)
        self.assertEqual(sw.ucli_idle_threshold(c, ""), 180)
        self.assertEqual(sw.ucli_idle_threshold(c, "1h"), 3000)

    def test_next_work_hint(self):
        p = lambda notes: sw.Project(name="cli", notes=notes)    # noqa: E731
        self.assertEqual(sw.next_work_hint(p("karar X\nSıradaki iş: B-listesi 3\n")), "B-listesi 3")
        self.assertEqual(sw.next_work_hint(p("sıradaki: yok")), "")
        self.assertEqual(sw.next_work_hint(p("sıradaki adımı düşün")), "notlardaki sıradaki iş")
        self.assertEqual(sw.next_work_hint(p(""), lambda n: 2), "TODO.md'deki ilk açık iş")
        self.assertEqual(sw.next_work_hint(p(""), lambda n: 0), "")
        self.assertEqual(sw.next_work_hint(p(""), lambda n: None), "")

    def test_finish_marker(self):
        self.assertEqual(sw.idle_finish_marker("bitti\nREADY FOR HANDOVER"), ("READY FOR HANDOVER", True))
        self.assertEqual(sw.idle_finish_marker("STEWARD-DONE: x"), ("STEWARD-DONE", False))
        self.assertEqual(sw.idle_finish_marker("Şu an yapacak iş yok."), ("yapacak iş yok", False))
        self.assertEqual(sw.idle_finish_marker("NO-STEWARD-DONE ya da STEWARD-DONE-CONFIRMED"), ("", False))
        self.assertEqual(sw.idle_finish_marker("sürüyor"), ("", False))


class PlanTest(unittest.TestCase):
    def test_nudge_with_next_work_single_line(self):
        acts, st = plan([view()], proj("a\nsıradaki: testleri yaz\nve ayrıca\nüçüncü"))
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])
        self.assertEqual(acts[0].payload["text"], "devam: testleri yaz" + sw.IDLE_STALE_NOTE_ESCAPE)   # not kaynaklı: bayatlık kaçışı var
        self.assertNotIn("\n", acts[0].payload["text"])
        self.assertEqual(st["ucli_idle"]["cli"]["n"], 1)

    def test_below_threshold_nothing(self):
        self.assertEqual(plan([view(idle=100)])[0], [])

    def test_threshold_follows_cache_ttl(self):
        self.assertEqual(plan([view(idle=1000, cache_ttl="1h")])[0], [])
        self.assertEqual([a.kind for a in plan([view(idle=3100, cache_ttl="1h")])[0]], ["idle_nudge"])
        self.assertEqual([a.kind for a in plan([view(idle=200, cache_ttl="5m")])[0]], ["idle_nudge"])

    def test_configurable_threshold_and_off(self):
        self.assertEqual(plan([view(idle=200)], c=cfg(ucli_idle_nudge_secs=300))[0], [])
        self.assertEqual(plan([view(idle=9999)], c=cfg(ucli_idle_nudge_secs=0))[0], [])

    def test_no_work_no_marker_does_nothing(self):
        self.assertEqual(plan([view()], proj(""))[0], [])
        self.assertEqual(plan([view()], proj("sıradaki: yok"))[0], [])

    def test_open_todo_counts_as_work(self):
        acts, _ = plan([view()], proj(""), open_work=lambda n: 3)
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])
        self.assertEqual(acts[0].payload["text"], "devam: TODO.md'deki ilk açık iş")

    def test_close_marker_with_work_requests_handover_then_reopen(self):
        acts, st = plan([view(last_assistant="işi bitirdim STEWARD-DONE")])
        self.assertEqual([(a.kind, a.payload["mode"], a.payload["pause"]) for a in acts], [("idle_close", "handover", False)])
        self.assertIn("cli", st["ho_pending"])           # sonraki tick'te READY -> respawn (fresh) mevcut yoldan
        self.assertNotIn("cli", st.get("ho_close", {}))

    def test_close_marker_without_work_pauses_and_closes_after_handover(self):
        acts, st = plan([view(last_assistant="yapacak iş yok")], proj(""))
        self.assertEqual([(a.kind, a.payload["mode"], a.payload["pause"]) for a in acts], [("idle_close", "handover", True)])
        self.assertEqual(st["ho_close"]["cli"], "cli")

    def test_ready_for_handover_already_written(self):
        acts, st = plan([view(last_assistant="özet\nREADY FOR HANDOVER")])
        self.assertEqual([(a.payload["mode"], a.payload["pause"]) for a in acts], [("respawn", False)])
        self.assertNotIn("ho_pending", st)
        acts, _ = plan([view(last_assistant="READY FOR HANDOVER")], proj(""))
        self.assertEqual([(a.payload["mode"], a.payload["pause"]) for a in acts], [("stop", True)])

    def test_observe_does_not_touch_handover_state(self):
        acts, st = plan([view(last_assistant="STEWARD-DONE")], c=cfg(mode="observe"))
        self.assertEqual([a.kind for a in acts], ["idle_close"])
        self.assertNotIn("ho_pending", st)
        apply, dry, _ = sw.observe_filter(acts, "observe", st, NOW)
        self.assertEqual((apply, [a.kind for a in dry]), ([], ["idle_close"]))     # yalnız would:
        acts, st = plan([view()], c=cfg(mode="observe"))
        apply, dry, _ = sw.observe_filter(acts, "observe", st, NOW)
        self.assertEqual((apply, [a.kind for a in dry]), ([], ["idle_nudge"]))

    def test_skips(self):
        for v in (view(busy=True), view(busy=None), view(cli="claude"), view(running=False), view(tmux=False),
                  view(name="cli_aj1"), view(subagent_active=True), view(subagent_unknown=True),
                  view(idle=0), view(host="yuhem")):
            self.assertEqual(plan([v])[0], [], v)
        self.assertEqual(plan([view(idle_since=0.0)])[0], [])           # boşta değil/bilinmiyor
        self.assertEqual(plan([view()], proj("sıradaki: x", phase="paused"))[0], [])
        self.assertEqual(plan([view()], proj("sıradaki: x", phase="done"))[0], [])
        self.assertEqual(plan([view()], {})[0], [])                      # kayıtsız oturum
        self.assertEqual(plan([view()], c=cfg(drain=True))[0], [])
        self.assertEqual(plan([view()], state={"ho_pending": {"cli": NOW}})[0], [])
        self.assertEqual(plan([view()], planned=[sw.Action("start", "cli")])[0], [])
        self.assertEqual(plan([view(name="degnekci")], proj("sıradaki: x", name="degnekci"))[0], [])

    def test_chain_limit_and_reset_on_activity(self):
        v = view()
        a1, st1 = plan([v])
        self.assertEqual(len(a1), 1)
        self.assertEqual(plan([v], state=st1, now=NOW + 60)[0], [])           # aynı boşta dönem, eşik dolmadı
        a2, st2 = plan([v], state=st1, now=NOW + 200)                         # eşik kadar sonra yeniden
        self.assertEqual((len(a2), st2["ucli_idle"]["cli"]["n"]), (1, 2))
        self.assertEqual(plan([v], state=st2, now=NOW + 500)[0], [])          # max 2: zincir kesildi
        busy_again = view(idle=0, idle_since=NOW + 600)                       # etkinlik oldu, yine boşa düştü
        a3, st3 = plan([busy_again], state=st2, now=NOW + 600 + 400)
        self.assertEqual((len(a3), st3["ucli_idle"]["cli"]["n"]), (1, 1))      # sayaç sıfırlandı


    def test_dry_counts_do_not_block_act(self):
        """5 Kas: dry'da 2 kez sayılan dürtme, act'e geçince zinciri kilitliyordu (copsdev 2 sa boşta)."""
        v = view()
        _, st = plan([v], c=cfg(ucli_idle="dry"))
        _, st = plan([v], state=st, c=cfg(ucli_idle="dry"), now=NOW + 200)
        self.assertEqual(st["ucli_idle"]["cli"], {"at": NOW + 200, "n": 2, "mode": "dry"})
        a, st2 = plan([v], state=st, now=NOW + 210)                           # act: eşik beklemeden ilk gerçek dürtme
        self.assertEqual((len(a), st2["ucli_idle"]["cli"]["n"], st2["ucli_idle"]["cli"]["mode"]), (1, 1, "act"))

    def test_legacy_record_without_mode_counts_as_dry(self):
        v = view()
        a, st = plan([v], state={"ucli_idle": {"cli": {"at": NOW - 10, "n": 2}}})
        self.assertEqual((len(a), st["ucli_idle"]["cli"]["n"]), (1, 1))

class ApplyTest(_Engine):
    """`_apply`: mevcut yollar (`_send`, handover/stop/respawn); gerçek spawn/tmux yok."""

    def setUp(self):
        super().setUp()
        self.sent = []
        self.typed = False
        patches = [
            mock.patch.object(ws, "_target", lambda *a, **k: None),
            mock.patch.object(ws, "_running", lambda name: NS(name=name, cli="ucli", pid=1, cwd="/w", sid=name)),
            mock.patch.object(ws, "is_tmux_backed", lambda pid: True),
            mock.patch.object(ws, "_box_has_typed_input", lambda name: self.typed),
            mock.patch.object(ws, "_send", lambda name, cli, text: self.sent.append((name, cli, text)) or True),
            mock.patch.object(ws, "_local_handover", lambda name, sid, lang: self.calls.append(("handover", name)) or {"ok": True}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        sw.upsert_project("cli", phase="planned", notes="sıradaki: testleri yaz")
        self.cfg = cfg()
        self.projects = sw.load_projects()

    def act(self, kind, **payload):
        return ws._apply(sw.Action(kind, "cli", "t", payload), self.cfg, self.projects)

    def test_nudge_is_sent_as_one_line(self):
        res = self.act("idle_nudge", text="devam:\nüç\nsatır", project="cli")
        self.assertTrue(res["ok"])
        self.assertEqual(self.sent, [("cli", "ucli", "devam: üç satır")])

    def test_nudge_skipped_when_input_box_has_text(self):
        self.typed = True
        res = self.act("idle_nudge", text="devam: x")
        self.assertFalse(res["ok"])
        self.assertEqual(self.sent, [])

    def test_close_handover_pauses_project_when_no_work(self):
        res = self.act("idle_close", mode="handover", pause=True, project="cli", marker="STEWARD-DONE")
        self.assertTrue(res["ok"])
        self.assertEqual(self.calls, [("handover", "cli")])
        self.assertEqual(sw.load_projects()["cli"].phase, "paused")

    def test_close_handover_keeps_phase_when_work_remains(self):
        self.act("idle_close", mode="handover", pause=False, project="cli")
        self.assertEqual(sw.load_projects()["cli"].phase, "planned")

    def test_close_stop_and_respawn_use_existing_paths(self):
        self.act("idle_close", mode="stop", pause=True, project="cli")
        self.assertEqual(self.calls, [("stop", "cli")])
        self.assertEqual(sw.load_projects()["cli"].phase, "paused")
        self.touched.clear()
        self.act("idle_close", mode="respawn", pause=False, project="cli")
        self.assertIn("cli", self.touched)          # `_ensure_running` (fresh, `_last_launch` cli_opts) yolu denendi

    def test_turn_failed_close_stops_and_asks_owner_once(self):
        res = self.act("idle_close", mode="stop", pause=False, project="cli", marker="turn_failed", n=2)
        self.assertTrue(res["ok"])
        self.assertEqual(self.calls, [("stop", "cli")])
        qs = [q for q in sw.load_questions() if q.project == "cli"]
        self.assertEqual(len(qs), 1)
        self.assertIn("başarısız", qs[0].text)
        self.assertEqual(sw.load_projects()["cli"].phase, "planned")      # paused DEĞİL: sahip karar verir

    def test_close_rejects_unknown_mode(self):
        self.assertFalse(self.act("idle_close", mode="kill", project="cli")["ok"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()

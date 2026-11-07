"""keepwarm planlayıcısı: boşta + işi olan + büyük bağlamlı oturuma TTL (60 dk) dolmadan dürtme; kesinlikle çalışmayana ASLA."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw, steward_keepwarm as skw  # noqa: E402

NOW = 1_800_000_000.0
PROJ = {"cli": sw.Project(name="cli", phase="planned")}


def view(name="cli", age_min=54, **kw):
    base = dict(running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=1.0,
                last_activity=NOW - age_min * 60, context_tokens=300_000)
    base.update(kw)
    return sw.SessionView(name=name, **base)


def cfg(**kw):
    c = sw.Config(enabled=True)
    c.keepwarm = "act"
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def plan(views, state=None, c=None, projects=PROJ, planned=()):
    return skw.plan_keepwarm(views, projects, state or {}, c or cfg(), NOW, list(planned))


class KeepwarmTest(unittest.TestCase):
    def test_pings_due_idle_big_active(self):
        acts, st = plan([view()])
        self.assertEqual([a.kind for a in acts], ["keepwarm"])
        self.assertEqual(st["keepwarm"]["cli"]["n"], 1)

    def test_not_due_window(self):
        for age in (10, 51, 58.5, 90):
            self.assertEqual(plan([view(age_min=age)])[0], [], age)

    def test_never_definitely_idle(self):
        for v in (view(busy=True), view(busy=None), view(subagent_active=True), view(subagent_unknown=True),
                  view(context_tokens=50_000), view(context_tokens=None), view(last_activity=0.0),
                  view(running=False), view(cli="codex"), view(tmux=False), view(host="yuhem")):
            self.assertEqual(plan([v])[0], [], v)
        for ph in ("done", "paused"):
            self.assertEqual(plan([view()], projects={"cli": sw.Project(name="cli", phase=ph)})[0], [], ph)
        self.assertEqual(plan([view("baska")])[0], [])                       # kayıtsız oturum
        self.assertEqual(plan([view()], c=cfg(drain=True))[0], [])            # yeni iş alma
        self.assertEqual(plan([view()], c=cfg(keepwarm="off"))[0], [])
        self.assertEqual(plan([view()], planned=[sw.Action("directive", "cli")])[0], [])   # aynı oturuma başka eylem var

    def test_no_repeat_in_same_window_and_chain_cap(self):
        acts, st = plan([view()])
        self.assertEqual(plan([view()], st)[0], [])                           # aynı pencerede tekrar yok (dry'da son etkinlik değişmez)
        # act: bir saat sonra dürtme turu son etkinlik oldu (gerçek etkinlik yok): 2. dürtme gider, 3.sü kesilir
        t1 = NOW + 3300
        st1 = {"keepwarm": {"cli": {"at": NOW, "n": 1}}}
        v = view(last_activity=NOW + 30)
        a2, st2 = skw.plan_keepwarm([v], PROJ, st1, cfg(), t1 + 0, [])
        self.assertEqual(a2[0].payload["n"], 2)
        a3, st3 = skw.plan_keepwarm([view(last_activity=t1 + 30)], PROJ, st2, cfg(keepwarm_chain_close="off"), t1 + 3300, [])
        self.assertEqual(a3[0].payload["n"], 3)                                # sınır 3 (sahip 7 Kas)
        a3b, _ = skw.plan_keepwarm([view(last_activity=t1 + 3330)], PROJ, st3, cfg(keepwarm_chain_close="off"), t1 + 6600, [])
        self.assertEqual(a3b, [])                                              # 4.sü kesilir (chain_close off: yalnız kes)
        # gerçek etkinlik zinciri sıfırlar
        a4, st4 = skw.plan_keepwarm([view(last_activity=t1 + 1800)], PROJ, st2, cfg(), t1 + 1800 + 54 * 60, [])
        self.assertEqual(a4[0].payload["n"], 1)

    def _text(self, notes="", last="", open_work=None, c=None):
        pr = {"cli": sw.Project(name="cli", phase="planned", notes=notes)}
        acts, _ = skw.plan_keepwarm([view(last_assistant=last)], pr, {}, c or cfg(), NOW, [], open_work=open_work)
        return acts[0].payload["text"]

    def test_text_default_when_no_work(self):
        self.assertEqual(self._text(), skw.KEEPWARM_TEXT)
        self.assertEqual(self._text(notes="sıradaki: yok"), skw.KEEPWARM_TEXT)

    def test_text_continue_when_work_pending(self):
        t = self._text(notes="x\nsıradaki: testleri\nyaz")
        self.assertEqual(t, "devam: testleri")
        self.assertNotIn("\n", t)
        # sahip 7 Kas: gerçek `sıradaki:` notu yoksa TODO'daki "ilk açık iş" iş emri GİTMEZ (ilk madde engelli/sahipte olabilir)
        self.assertEqual(self._text(open_work=lambda p: 2), skw.KEEPWARM_TEXT)
        self.assertEqual(self._text(notes="sıradaki işler var", open_work=lambda p: 2), skw.KEEPWARM_TEXT)

    def test_text_light_ping_when_finished(self):
        for last in ("READY FOR HANDOVER", "STEWARD-DONE", "Yapacak iş yok."):
            self.assertEqual(self._text(notes="sıradaki: a", last=last), skw.KEEPWARM_TEXT, last)

    def test_empty_last_assistant_is_not_finished(self):
        self.assertEqual(self._text(notes="sıradaki: a", last=""), "devam: a")

    def test_dry_mode_payload_has_text(self):
        pr = {"cli": sw.Project(name="cli", phase="planned", notes="sıradaki: a")}
        acts, _ = skw.plan_keepwarm([view()], pr, {}, cfg(keepwarm="dry"), NOW, [])
        self.assertEqual(acts[0].payload["text"], "devam: a")


if __name__ == "__main__":
    unittest.main()


OWNER_TXT = "Kalan iş sahipte, bekliyorum"


def ov(*a, **kw):
    kw.setdefault("last_assistant", OWNER_TXT)
    return view(*a, **kw)


class ChainCloseTest(unittest.TestCase):
    FULL = {"keepwarm": {"cli": {"at": NOW - 3300, "n": 3}}}

    def _plan(self, mode="act", proj=None, state=None, **vk):
        c = cfg(keepwarm_chain_close=mode)
        c.mode = "act"
        return skw.plan_keepwarm([ov(last_activity=NOW - 54 * 60 + 0, **vk)], {"cli": proj or sw.Project(name="cli", phase="planned")},
                                 dict(state or self.FULL), c, NOW, [])

    def test_default_dry_and_max3(self):
        self.assertEqual(sw.Config().keepwarm_chain_close, "dry")
        self.assertEqual(sw.Config().keepwarm_max_consecutive, 3)

    def test_act_hands_over_closes_and_defers_pause(self):
        acts, st = self._plan("act")
        self.assertEqual([(a.kind, a.payload["mode"], a.payload["marker"], a.payload["pause"]) for a in acts],
                         [("idle_close", "handover", "keepwarm_chain", False)])
        self.assertIn("3 dürtmede iş yok", acts[0].payload["pause_reason"])
        self.assertEqual(list(st["ho_pending"]), ["cli"])
        self.assertEqual(st["ho_close"], {"cli": "cli"})
        self.assertIn("3 dürtmede iş yok", st["ho_pause"]["cli"])
        # aynı dönem tekrar üretmez
        again, _ = skw.plan_keepwarm([ov(last_activity=NOW - 54 * 60)], {"cli": sw.Project(name="cli", phase="planned")}, st, cfg(keepwarm_chain_close="act"), NOW + 120, [])
        self.assertEqual(again, [])

    def test_dry_writes_no_handover_state_and_does_not_block_act(self):
        acts, st = self._plan("dry")
        self.assertEqual(len(acts), 1)
        self.assertNotIn("ho_pending", st)
        self.assertNotIn("ho_pause", st)
        act, _ = skw.plan_keepwarm([ov(last_activity=NOW - 54 * 60)], {"cli": sw.Project(name="cli", phase="planned")}, st, cfg(keepwarm_chain_close="act"), NOW + 60, [])
        self.assertEqual(len(act), 1)          # dry'da sayılan kayıt act'i KİLİTLEMEZ

    def test_exempt_off_unregistered_and_paused_only_cut(self):
        for proj in (sw.Project(name="copsdev", phase="planned"), sw.Project(name="cli", phase="planned", notes="Devam Etmeli: sürekli")):
            v = ov(name=proj.name, last_activity=NOW - 54 * 60)
            state = {"keepwarm": {proj.name: {"at": NOW - 3300, "n": 3}}}
            self.assertEqual(skw.plan_keepwarm([v], {proj.name: proj}, state, cfg(keepwarm_chain_close="act"), NOW, [])[0], [], proj.name)
        self.assertEqual(self._plan("off")[0], [])
        self.assertEqual(skw.plan_keepwarm([ov("baska", last_activity=NOW - 54 * 60)], PROJ, self.FULL, cfg(keepwarm_chain_close="act"), NOW, [])[0], [])
        self.assertEqual(self._plan("act", proj=sw.Project(name="cli", phase="paused"))[0], [])

    def test_real_activity_resets_chain_no_close(self):
        acts, _ = skw.plan_keepwarm([ov(last_activity=NOW - 54 * 60)], PROJ, {"keepwarm": {"cli": {"at": NOW - 7200, "n": 3}}},
                                    cfg(keepwarm_chain_close="act"), NOW, [])
        self.assertEqual([a.kind for a in acts], ["keepwarm"])


class OwnerWaitTest(unittest.TestCase):
    def test_owner_wait(self):
        self.assertTrue(sw.owner_wait("Kalan iş sahipte, bekliyorum"))
        self.assertTrue(sw.owner_wait("Waiting on the owner"))
        self.assertFalse(sw.owner_wait("testleri yazıyorum"))


class ConditionalNoteTest(unittest.TestCase):
    def test_detect(self):
        for t in ("SAHİP cevap gelirse A'yı yap", "deney bitince raporla", "if the build passes, ship", "BEKLEME: dış iş", "X olursa Y", "eğer test geçerse merge"):
            self.assertTrue(sw.is_conditional_note(t), t)
        for t in ("testleri yaz", "TODO.md'deki 3. maddeyi uygula", "refactor steward.py"):
            self.assertFalse(sw.is_conditional_note(t), t)

    def test_conditional_note_gives_no_hint_and_plain_keepwarm(self):
        pr = sw.Project(name="cli", phase="planned", notes="sıradaki: sahip onaylarsa A'yı deploy et")
        self.assertEqual(sw.next_work_hint(pr), "")
        self.assertEqual(skw.keepwarm_text(pr, view()), skw.KEEPWARM_TEXT)
        pr2 = sw.Project(name="cli", phase="planned", notes="x\\nsıradaki iş var ama X olursa Y")
        self.assertEqual(sw.next_work_hint(pr2), "")
        self.assertEqual(sw.next_work_hint(sw.Project(name="cli", notes="sıradaki: testleri yaz")), "testleri yaz")


class ChainCloseWarmTest(unittest.TestCase):
    """mtsyn 7 Kas 16:02: 3. dürtme gitti (n=3) ama kapanış ancak sonraki 52 dk eşiğinde (~16:55) üretilecekti."""
    AT = NOW - 20 * 60

    def _plan(self, n, last, mode="dry"):
        c = cfg(keepwarm_chain_close=mode)
        c.mode = "act"
        return skw.plan_keepwarm([ov(last_activity=last)], {"cli": sw.Project(name="cli", phase="planned")},
                                 {"keepwarm": {"cli": {"at": self.AT, "n": n}}}, c, NOW, [])

    def test_full_chain_closes_while_cache_warm(self):
        acts, _ = self._plan(3, self.AT + 40)             # dürtmenin kendi turu (slack içinde), 20 dk boşta
        self.assertEqual([(a.kind, a.payload["marker"]) for a in acts], [("idle_close", "keepwarm_chain")])

    def test_act_sets_handover_state(self):
        acts, st = self._plan(3, self.AT + 40, "act")
        self.assertEqual(len(acts), 1)
        self.assertEqual(list(st["ho_pending"]), ["cli"])

    def test_real_activity_after_nudge_no_action_before_due(self):
        self.assertEqual(self._plan(3, self.AT + 600)[0], [])      # sahip/oturum gerçekten konuştu: zincir sıfır, 52 dk bekle

    def test_incomplete_chain_waits_for_due(self):
        self.assertEqual(self._plan(2, self.AT + 40)[0], [])       # 2. dürtmeden sonra kapanış YOK, 3. dürtme sonraki pencerede


class NotOwnerWaitTest(unittest.TestCase):
    """Sahip kararı (7 Kas): kapanış YALNIZ iş sahipte bekliyorsa; menzilui (tunnel GetUsage bekliyor) yanlış pozitifti."""
    AT = NOW - 20 * 60

    def _plan(self, txt, owner_projects=None, mode="dry"):
        c = cfg(keepwarm_chain_close=mode)
        c.mode = "act"
        return skw.plan_keepwarm([view(last_activity=self.AT + 40, last_assistant=txt)], PROJ,
                                 {"keepwarm": {"cli": {"at": self.AT, "n": 3}}}, c, NOW, [], owner_projects=owner_projects)

    def test_waiting_on_other_project_not_closed(self):
        acts, st = self._plan("tunnel GetUsage çıktısını bekliyorum")
        self.assertEqual(acts, [])
        self.assertNotIn("ho_pending", st)

    def test_open_owner_question_closes(self):
        self.assertEqual([a.kind for a in self._plan("tunnel bekliyorum", owner_projects={"cli"})[0]], ["idle_close"])

    def test_owner_phrase_closes(self):
        self.assertEqual([a.kind for a in self._plan("Kalan iş sahipte")[0]], ["idle_close"])

    def test_question_of_other_project_does_not_count(self):
        self.assertEqual(self._plan("bekliyorum", owner_projects={"baska"})[0], [])

"""todo_triage: TODO'da sahipsiz açık madde var ama oturum 'sıradaki: yok'/sahipte diyor -> BİR kez ayıklama mesajı (sahibe bağlıları TBD'ye taşı);
aynı TODO sha'sında tekrar yok, TODO değişince yeniden mümkün, açık=0'da hiç. Canlı servis/tmux YOK."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

NOW = 1_000_000.0
NONE_TXT = "Kalan her şey sahibe bağlı.\nSTEWARD-NEXT: yok"
OWNER_TXT = "Bu iş sahibin kararında, sahipte."


def _view(txt=NONE_TXT, **kw):
    base = dict(running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=1.0, last_activity=NOW - 3100, last_assistant=txt)
    base.update(kw)
    return sw.SessionView(name="p", **base)


class Plan(unittest.TestCase):
    def plan(self, views, state=None, n_open=23, sha="aaa", mode="act", now=NOW):
        projs = {"p": sw.Project(name="p", phase="planned", cadence_minutes=0)}
        cfg = sw.Config(enabled=True, mode="act", claude_idle=mode)
        return sw.plan_claude_idle(views, projs, state or {}, cfg, now, [], open_work=lambda _p: n_open, owner_todo=lambda _p: 0,
                                   todo_sha=lambda _p: sha)

    def test_mismatch_sends_one_triage_not_continue(self):
        acts, st = self.plan([_view()])
        self.assertEqual([a.kind for a in acts], ["todo_triage"])
        t = acts[0].payload["text"]
        self.assertIn("TOBEDECIDED.md", t)
        self.assertIn("STEWARD-NEXT: yok", t)
        self.assertEqual(acts[0].payload["todo_open"], 23)
        self.assertEqual(st["todo_triage"]["p"]["sha"], "aaa")

    def test_owner_wait_text_also_triggers(self):
        acts, _ = self.plan([_view(OWNER_TXT)])
        self.assertEqual([a.kind for a in acts], ["todo_triage"])

    def test_same_sha_never_again_and_no_continue_nudge(self):
        acts, st = self.plan([_view()])
        v2 = _view(last_activity=NOW + 7200 - 3100)
        acts2, st2 = self.plan([v2], st, now=NOW + 7200)
        self.assertEqual(acts2, [])                 # tekrar yok, "devam" dürtmesi de yok
        acts3, _ = self.plan([_view(last_activity=NOW + 90000 - 3100)], st2, now=NOW + 90000)
        self.assertEqual(acts3, [])                 # saatler sonra da (TODO aynı)

    def test_changed_todo_allows_again(self):
        _, st = self.plan([_view()])
        acts, st2 = self.plan([_view(last_activity=NOW + 7200 - 3100)], st, sha="bbb", now=NOW + 7200)
        self.assertEqual([a.kind for a in acts], ["todo_triage"])
        self.assertEqual(st2["todo_triage"]["p"]["sha"], "bbb")

    def test_zero_open_sends_nothing(self):
        self.assertEqual(self.plan([_view()], n_open=0)[0], [])

    def test_no_sha_available_sends_nothing_extra(self):
        acts, _ = self.plan([_view()], sha="")
        self.assertNotIn("todo_triage", [a.kind for a in acts])

    def test_dry_and_act_counted_separately(self):
        _, st = self.plan([_view()], mode="dry")
        acts, _ = self.plan([_view(last_activity=NOW + 7200 - 3100)], st, mode="act", now=NOW + 7200)
        self.assertEqual([a.kind for a in acts], ["todo_triage"])       # dry kaydı act'ı engellemez

    def test_session_with_real_work_still_gets_normal_nudge(self):
        acts, _ = self.plan([_view("Bitirdim, şimdi sıradaki işe geçiyorum.")])
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])        # uyumsuzluk yok: eski davranış

    def test_busy_or_recent_untouched(self):
        self.assertEqual(self.plan([_view(busy=True)])[0], [])
        self.assertEqual(self.plan([_view(last_activity=NOW - 60)])[0], [])

    def test_explain_reason(self):
        projs = {"p": sw.Project(name="p", phase="planned", cadence_minutes=0)}
        r = sw.explain_idle(projs["p"], [_view()], projs, {"todo_triage": {"p": {"sha": "aaa", "at": NOW}}}, sw.Config(claude_idle="act"), NOW,
                            [], [], None, lambda _p: 23)
        self.assertEqual(r["code"], "todo_triage")

    def test_observe_list_and_preamble_rule(self):
        self.assertIn("todo_triage", sw.OBSERVE_SKIPPED)
        self.assertIn("TODO/TBD kuralı", sw._PROTOCOL_TR)
        self.assertIn("TODO/TBD rule", sw._PROTOCOL_EN)
        self.assertNotIn("private ise yerelde kalır", sw._PROTOCOL_TR)   # eski hafıza cümlesi gitti


class Sha(unittest.TestCase):
    def test_sha_changes_with_content_and_unknown_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            p = os.path.join(d, "TODO.md")
            open(p, "w", encoding="utf-8").write("- [ ] a\n")
            projs = {"p": sw.Project(name="p", phase="planned"), "r": sw.Project(name="r", phase="planned", host="h")}
            orig = ws._cwd_resolver
            ws._cwd_resolver = lambda: (lambda n: d)
            try:
                f = ws._todo_sha_of(projs)
                a = f("p")
                self.assertEqual(len(a), 64)
                self.assertEqual(f("p"), a)
                open(p, "w", encoding="utf-8").write("- [ ] a\n- [ ] b\n")
                self.assertNotEqual(f("p"), a)
                self.assertEqual(f("r"), "")            # uzak
                self.assertEqual(f("yok"), "")
            finally:
                ws._cwd_resolver = orig

    def test_shared_todo_does_not_reopen_other_projects_closed_as_no_work(self):
        """27 Kas: Rust izlerinin TODO.md'si ana projenin dosyasına symlink; her düzenleme "iş yok" kapatılan hepsini `todo_changed`
        ile yeniden açtı (günde 51 açılış). Başka projenin TODO'su bu projenin tetiği değildir (açık iş sayacıyla aynı kural)."""
        with tempfile.TemporaryDirectory() as d:
            main, iz = os.path.join(d, "ana"), os.path.join(d, "iz")
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", main]
            subprocess.run(["git", "init", "-q", main], check=True)
            subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "ilk"], check=True)
            subprocess.run(git + ["worktree", "add", "-q", iz, "-b", "iz"], check=True)
            todo = os.path.join(main, "TODO.md")
            open(todo, "w", encoding="utf-8").write("- [ ] a\n")
            os.symlink(todo, os.path.join(iz, "TODO.md"))
            projs = {"ana": sw.Project(name="ana", phase="paused"), "iz": sw.Project(name="iz", phase="paused")}
            orig = ws._cwd_resolver
            ws._cwd_resolver = lambda: {"ana": main, "iz": iz}.get
            try:
                f = ws._todo_sha_of(projs)
                before = {n: f(n) for n in projs}
                state = {"no_work_paused": {n: {"at": NOW, "sha": before[n] or "eski-kayit"} for n in projs}}
                open(todo, "a", encoding="utf-8").write("- [ ] ana projenin yeni maddesi\n")
                acts = ws.snw.plan_no_work_reopen(projs, state, NOW + 60, {}, f)
                self.assertEqual([(a.name, a.payload["trigger"]) for a in acts], [("ana", "todo_changed")])
                self.assertEqual(f("iz"), "")
                # ana proje kayıtlı değilse dosyanın tek sahibi iz: tetik sürer
                self.assertEqual(len(ws._todo_sha_of({"iz": projs["iz"]})("iz")), 64)
            finally:
                ws._cwd_resolver = orig


if __name__ == "__main__":
    unittest.main()

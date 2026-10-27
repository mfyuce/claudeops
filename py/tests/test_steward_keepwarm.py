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
        a3, _ = skw.plan_keepwarm([view(last_activity=t1 + 30)], PROJ, st2, cfg(), t1 + 3300, [])
        self.assertEqual(a3, [])
        # gerçek etkinlik zinciri sıfırlar
        a4, st4 = skw.plan_keepwarm([view(last_activity=t1 + 1800)], PROJ, st2, cfg(), t1 + 1800 + 54 * 60, [])
        self.assertEqual(a4[0].payload["n"], 1)


if __name__ == "__main__":
    unittest.main()

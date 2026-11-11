"""TODO.md'deki sahibe bağlı etiketli maddeler: açık iş sayılmaz, `owner_in_todo` ayrı sayılır, boştaki yerel claude oturumuna
24 sa'te en çok bir kez "TOBEDECIDED'a taşı" gider (`owner_todo_move`), panel nedeninde sayı görünür. Canlı servis/tmux YOK."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

NOW = 1_000_000.0
TODO = """# TODO
- [ ] normal iş
- [ ] (sahip) onay lazım
- [ ] SAHİPTE: parola
- [ ] SAHIPTE: dosya
- [ ] sahipte bu
- [ ] DIŞ GİRDİ BEKLİYOR: veri
- [ ] DIS GIRDI bekliyor
- [ ] sahip kararı bekliyor: seçenek
- [ ] Sahip Kararı Bekliyor
- [x] SAHİPTE: kapalı olan sayılmaz
- [ ] ikinci normal iş
"""


class Regex(unittest.TestCase):
    def test_tags(self):
        for t in ("SAHİPTE", "SAHIPTE", "sahipte", "(sahip)", "DIŞ GİRDİ", "DIS GIRDI", "dış girdi bekliyor", "sahip kararı bekliyor",
                  "sahip karari bekliyor", "Sahip Kararı Bekliyor"):
            self.assertTrue(sw.OWNER_TODO_LINE_RE.search("- [ ] " + t), t)
        for t in ("sahipsiz iş", "kalite girdisi"):
            self.assertFalse(sw.OWNER_TODO_LINE_RE.search("- [ ] " + t), t)

    def test_wait_re_covers_new_and_old(self):
        self.assertTrue(sw.OWNER_WAIT_LINE_RE.search("- [ ] SAHİPTE x"))
        self.assertTrue(sw.OWNER_WAIT_LINE_RE.search("- [ ] STEWARD-ASK x"))


class Counting(unittest.TestCase):
    def test_scan(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            with open(os.path.join(d, "TODO.md"), "w", encoding="utf-8") as f:
                f.write(TODO)
            projs = {"p": sw.Project(name="p", phase="planned")}
            orig = ws._cwd_resolver
            ws._cwd_resolver = lambda: (lambda n: d)
            try:
                self.assertEqual(ws._scan_todo(projs, "p"), (2, 8))
                self.assertEqual(ws._open_work_of(projs)("p"), 2)
                self.assertEqual(ws._owner_todo_of(projs)("p"), 8)
                projs["r"] = sw.Project(name="r", phase="planned", host="h")
                self.assertIsNone(ws._owner_todo_of(projs)("r"))      # uzak proje: yok
            finally:
                ws._cwd_resolver = orig


def _view(**kw):
    base = dict(running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=1.0, last_activity=NOW - 3100, last_assistant="")
    base.update(kw)
    return sw.SessionView(name="p", **base)


def _plan(views, state=None, mode="act", n=3, now=NOW, proj=None):
    projs = {"p": proj or sw.Project(name="p", phase="planned", cadence_minutes=0)}
    cfg = sw.Config(enabled=True, mode="act", claude_idle=mode)
    return sw.plan_claude_idle(views, projs, state or {}, cfg, now, [], owner_todo=lambda _p: n)


class Move(unittest.TestCase):
    def test_sent_once_per_24h(self):
        acts, st = _plan([_view()])
        self.assertEqual([a.kind for a in acts], ["owner_todo_move"])
        self.assertIn("3 maddeyi TOBEDECIDED", acts[0].payload["text"])
        self.assertEqual(st["owner_todo_move"]["p"]["n"], 3)
        # oturum yanıtladı, yine boşta: 24 sa dolmadan ikinci mesaj YOK
        v2 = _view(last_activity=NOW + 3600 - 3100)
        acts2, _ = _plan([v2], st, now=NOW + 3600)
        self.assertEqual(acts2, [])
        # 24 sa sonra tekrar
        v3 = _view(last_activity=NOW + 90000 - 3100)
        acts3, _ = _plan([v3], st, now=NOW + 90000)
        self.assertEqual([a.kind for a in acts3], ["owner_todo_move"])

    def test_zero_remote_busy_and_off(self):
        self.assertEqual(_plan([_view()], n=0)[0], [])
        self.assertEqual(_plan([_view(busy=True)])[0], [])
        self.assertEqual(_plan([_view(host="h")])[0], [])
        self.assertEqual(_plan([_view()], mode="off")[0], [])
        self.assertEqual(_plan([_view(last_activity=NOW - 60)])[0], [])           # eşik dolmadı
        self.assertEqual(_plan([_view(last_assistant="STEWARD-ASK: ?")])[0], [])  # soru sormuş: normal kurallar

    def test_done_project_skipped(self):
        self.assertEqual(_plan([_view()], proj=sw.Project(name="p", phase="paused"))[0], [])

    def test_dry_mode_does_not_lock_act(self):
        _, st = _plan([_view()], mode="dry")
        acts, _ = _plan([_view()], st, mode="act")
        self.assertEqual([a.kind for a in acts], ["owner_todo_move"])

    def test_observe_skips_kind(self):
        self.assertIn("owner_todo_move", sw.OBSERVE_SKIPPED)


class Explain(unittest.TestCase):
    def test_count_in_why(self):
        p = sw.Project(name="p", phase="planned", cadence_minutes=60)
        out = sw.explain_idle_all([], {"p": p}, {}, sw.Config(), NOW, [], owner_todo=lambda _p: 6)
        self.assertEqual(out["p"]["owner_in_todo"], 6)
        out = sw.explain_idle_all([], {"p": p}, {}, sw.Config(), NOW, [], owner_todo=lambda _p: 0)
        self.assertNotIn("owner_in_todo", out["p"])


if __name__ == "__main__":
    unittest.main()

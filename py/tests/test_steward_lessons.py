"""ucli dersleri köprüsü: reviewer `ucli-lessons.md` -> ucli projesinin çalışan oturumuna direktif (başka reponun dosyasına yazılmaz).
Saf planlayıcı + iletim; gerçek oturum/model YOK."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw, steward_lessons as sl  # noqa: E402
from claudeops.commands import web_steward  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402

NOW = 1_800_000_000.0
AUTO = sl.AUTO_TAG


def view(name="cli", **kw):
    base = dict(running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=1.0, last_activity=NOW - 600)
    base.update(kw)
    return sw.SessionView(name=name, **base)


PROJ = {"cli": sw.Project(name="cli")}


class ReadTest(unittest.TestCase):
    def test_only_auto_tagged_lines_and_dedup(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, sl.LESSONS_FILE), "w") as f:
            f.write("- 2026-10-24 elle yazılmış not\n" + AUTO + "a\n" + AUTO + "b\n" + AUTO + "a\nbaşlıksız satır\n")
        got = sl.read_lessons([d, "/yok/yer"])
        self.assertEqual([ln for _, ln in got], [AUTO + "a", AUTO + "b"])


class PlanTest(unittest.TestCase):
    def lessons(self, *xs):
        return [(sl.line_hash(AUTO + x), AUTO + x) for x in xs]

    def plan(self, views, lessons, state=None, project="cli", planned=()):
        return sl.plan_lesson_deliveries(views, PROJ, lessons, state or {}, NOW, project, list(planned))

    def test_sends_one_action_with_batch_limit(self):
        ls = self.lessons(*[f"d{i}" for i in range(8)])
        acts, st = self.plan([view()], ls)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].kind, "deliver_lesson")
        self.assertEqual(acts[0].name, "cli")
        self.assertEqual(len(acts[0].payload["hashes"]), sl.BATCH_MAX)
        self.assertEqual(st["last_directive_at"]["cli"], NOW)

    def test_gates(self):
        ls = self.lessons("x")
        for v in (view(busy=True), view(subagent_active=True), view(subagent_unknown=True), view(running=False)):
            self.assertEqual(self.plan([v], ls)[0], [], v)
        self.assertEqual(self.plan([], ls)[0], [])                                   # oturum yok: BEKLER, açılmaz
        self.assertEqual(self.plan([view()], ls, project="")[0], [])                   # kapalı
        self.assertEqual(self.plan([view()], ls, project="baska")[0], [])              # proje bu kimliğin değil
        self.assertEqual(self.plan([view()], ls, planned=[sw.Action("directive", "cli", "x", {})])[0], [])

    def test_sent_lines_not_resent_and_failures_capped(self):
        ls = self.lessons("a", "b")
        st = {"lessons_sent": [ls[0][0]]}
        acts, _ = self.plan([view()], ls, st)
        self.assertEqual(acts[0].payload["hashes"], [ls[1][0]])
        st = {"lessons_sent": [ls[0][0]], "lessons_fail": {ls[1][0]: sl.FAIL_MAX}}
        self.assertEqual(self.plan([view()], ls, st)[0], [])


class DeliverTest(_Tmp):
    def action(self, lines):
        return sw.Action("deliver_lesson", "cli", "lesson", {"project": "cli", "hashes": [sl.line_hash(x) for x in lines], "lines": lines})

    def test_success_marks_sent_once_and_failure_counts(self):
        cfg = sw.Config(enabled=True)
        proj = sw.Project(name="cli")
        lines = [AUTO + "ders bir", AUTO + "ders iki"]
        sent = []
        with mock.patch.object(web_steward, "_give_directive", lambda p, text, **k: sent.append(text) or {"ok": True}):
            res = web_steward._deliver_lesson(self.action(lines), cfg, {"cli": proj})
        self.assertTrue(res["ok"])
        self.assertIn("ders bir", sent[0])
        st = sw.load_state(sw.paths_for(cfg.sid))
        self.assertEqual(set(st["lessons_sent"]), {sl.line_hash(x) for x in lines})
        ls = [(sl.line_hash(x), x) for x in lines]
        self.assertEqual(sl.pending(ls, st), [])                                       # bir daha planlanmaz

        with mock.patch.object(web_steward, "_give_directive", lambda p, text, **k: {"ok": False, "error": "busy"}):
            web_steward._deliver_lesson(self.action([AUTO + "yeni"]), cfg, {"cli": proj})
        st = sw.load_state(sw.paths_for(cfg.sid))
        self.assertEqual(st["lessons_fail"][sl.line_hash(AUTO + "yeni")], 1)

    def test_lessons_reads_reviewer_workspaces_only_when_enabled(self):
        cfg = sw.Config(enabled=True)
        cfg.lessons_project = "off"
        self.assertEqual(sl.target_project("Off"), "")
        self.assertEqual(sl.target_project(" cli "), "cli")
        self.assertEqual(web_steward._lessons(cfg), [])


if __name__ == "__main__":
    unittest.main()

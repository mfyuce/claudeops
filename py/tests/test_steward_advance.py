"""İlerletme değnekçisi: onaylı (`exported`) review bulguları -> KİMLİĞİN projesinin çalışan oturumuna direktif. Saf planlayıcı,
TODO satırı durumu, iletim ve tick e2e (sahte oturum/direktif; canlı model/oturum YOK)."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_steward_engine_multi import _Engine, _view  # noqa: E402
from claudeops import review as rv, settings, steward as sw, steward_advance as sa  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

NOW = 1_800_000_000.0


def cand(fid="p:a:R-1", project="cli", sev="P2", todo="open", **kw):
    return dict({"id": fid, "project": project, "severity": sev, "where": "a.py:1", "title": "t", "todo": todo}, **kw)


def view(name="cli", **kw):
    base = dict(running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=1.0, last_activity=NOW - 600)
    base.update(kw)
    return sw.SessionView(name=name, **base)


PROJ = {"cli": sw.Project(name="cli")}


class TodoStatusTest(unittest.TestCase):
    def test_open_done_missing_and_path_safety(self):
        d = os.path.realpath(tempfile.mkdtemp())
        todo = os.path.join(d, "TODO.md")
        with open(todo, "w") as f:
            f.write("- [ ] (review p:a:R-1) [P2] a.py:1: x\n- [x] (review p:a:R-2) [P2] b.py:1: y\n* [X] (review p:a:R-3) z\n")
        self.assertEqual(sa.todo_status(todo, d, "p:a:R-1"), "open")
        self.assertEqual(sa.todo_status(todo, d, "p:a:R-2"), "done")
        self.assertEqual(sa.todo_status(todo, d, "p:a:R-3"), "done")
        self.assertEqual(sa.todo_status(todo, d, "p:a:R-9"), "missing")
        self.assertEqual(sa.todo_status(todo, tempfile.mkdtemp(), "p:a:R-1"), "missing")       # proje klasörü DIŞINDA
        self.assertEqual(sa.todo_status("", d, "p:a:R-1"), "missing")
        link = os.path.join(d, "L.md")
        outside = os.path.join(tempfile.mkdtemp(), "x.md")
        with open(outside, "w") as f:
            f.write("- [ ] (review p:a:R-1) kaçış\n")
        os.symlink(outside, link)
        self.assertEqual(sa.todo_status(link, d, "p:a:R-1"), "missing")                        # symlink kaçışı

    def test_candidates_only_exported(self):
        d = os.path.realpath(tempfile.mkdtemp())
        todo = os.path.join(d, "TODO.md")
        with open(todo, "w") as f:
            f.write("- [ ] (review f1) x\n")
        data = {"f1": {"project": "cli", "state": "exported", "exported_to": todo, "severity": "P1", "title": "a  b"},
                "f2": {"project": "cli", "state": "approved", "exported_to": todo},
                "f3": {"project": "cli", "state": "verified"}}
        got = sa.candidates([data], lambda n: d)
        self.assertEqual([(c["id"], c["todo"], c["title"]) for c in got], [("f1", "open", "a b")])

    def test_secret_findings_are_held_back(self):
        d = os.path.realpath(tempfile.mkdtemp())
        data = {"f1": {"project": "ncs", "state": "exported", "title": "Veritabanı parolası kaynak koduna gömülü"},
                "f2": {"project": "ncs", "state": "exported", "title": "DB password hardcoded", "where": "a.py:6"},
                "f3": {"project": "ncs", "state": "exported", "title": "Arapça anahtar kelime kaçışsız"}}
        self.assertEqual([c["id"] for c in sa.candidates([data], lambda n: d)], ["f3"])


class PlanTest(unittest.TestCase):
    def plan(self, views, cands, state=None, planned=(), projects=PROJ, limit=1):
        return sa.plan_advance_deliveries(views, projects, cands, state or {}, NOW, list(planned), None, limit)

    def test_p1_first_batch_limit_and_single_action(self):
        cs = [cand(f"f{i}", sev="P3") for i in range(5)] + [cand("fp1", sev="P1")]
        acts, st = self.plan([view()], cs)
        self.assertEqual(len(acts), 1)
        rows = acts[0].payload["rows"]
        self.assertEqual(len(rows), sa.BATCH_MAX)
        self.assertEqual(rows[0]["id"], "fp1")
        self.assertEqual(st["last_directive_at"]["cli"], NOW)

    def test_only_own_open_and_idle(self):
        self.assertEqual(self.plan([view()], [cand(project="baska")])[0], [])                 # projesi bu kimliğin değil
        self.assertEqual(self.plan([view()], [cand(todo="done")])[0], [])
        self.assertEqual(self.plan([view()], [cand(todo="missing")])[0], [])
        for v in (view(busy=True), view(subagent_active=True), view(subagent_unknown=True), view(running=False)):
            self.assertEqual(self.plan([v], [cand()])[0], [], v)
        self.assertEqual(self.plan([], [cand()])[0], [])                                       # oturum yok: BEKLER
        self.assertEqual(self.plan([view()], [cand()], planned=[sw.Action("directive", "cli", "x", {})])[0], [])

    def test_resend_policy(self):
        c = [cand("f1")]
        self.assertEqual(self.plan([view()], c, {"advance_sent": {"f1": {"at": NOW - 3600, "n": 1}}})[0], [])      # 12 saat dolmadı
        self.assertEqual(len(self.plan([view()], c, {"advance_sent": {"f1": {"at": NOW - 13 * 3600, "n": 1}}})[0]), 1)
        self.assertEqual(self.plan([view()], c, {"advance_sent": {"f1": {"at": NOW - 99 * 3600, "n": sa.SEND_MAX}}})[0], [])

    def test_message_carries_authority_limits(self):
        m = sa.build_advance_message([cand("f1", sev="P1", title="parola")], "tr")
        for needle in ("f1", "P1", "parola", "YALNIZ", "CLAUDE.md", "dokunma"):
            self.assertIn(needle, m)
        self.assertIn("ONLY", sa.build_advance_message([cand()], "en"))


class TickE2E(_Engine):
    """Gerçek tick: `ilerlet` benzeri bayrak açık kimlik, reviewer'ın `exported` bulgusu, projenin TODO.md'si."""

    def setUp(self):
        super().setUp()
        settings.save_settings({
            "steward": {"enabled": "on", "mode": "act", "card_refresh": "off", "advance_findings": "on"},
            "stewards": {"rvw": {"enabled": "on", "mode": "act", "role": "reviewer"}}})
        self.given = []
        self.proj_dir = os.path.realpath(self.dir.name)
        self.todo = os.path.join(self.proj_dir, "TODO.md")
        with open(self.todo, "w") as f:
            f.write("- [ ] (review cli:r:R-1) [P1] a.py:1: gerçek bulgu\n")
        for p in (mock.patch.object(ws, "_give_directive", self._give),
                  mock.patch.object(ws, "_project_cwd", lambda name: self.proj_dir),
                  mock.patch.object(ws, "_cwd_resolver", lambda: (lambda name: self.proj_dir))):
            p.start()
            self.addCleanup(p.stop)
        sw.upsert_project("cli", phase="planned", cadence_minutes=0)
        rp = sw.paths_for("rvw")
        os.makedirs(rp.root, exist_ok=True)
        rv.save_findings(rp, {"cli:r:R-1": {"project": "cli", "state": "exported", "severity": "P1", "where": "a.py:1",
                                            "title": "gerçek bulgu", "exported_to": self.todo},
                              "cli:r:R-2": {"project": "cli", "state": "verified", "severity": "P1", "where": "b.py:2", "title": "onaysız"}})

    def _give(self, project, text, **kw):
        self.given.append((project.name, text, kw))
        return {"ok": True, "name": kw.get("session_name") or project.name}

    def test_exported_finding_delivered_once_then_done_line_stops_it(self):
        self.views = [_view("cli", last_activity=time.time())]
        res = ws.tick_once("manual", "default")
        self.assertIn("deliver_findings", [a["kind"] for a in res["actions"]])
        name, text, kw = self.given[0]
        self.assertIn("cli:r:R-1", text)
        self.assertNotIn("R-2", text)                                          # onaysız (verified) bulgu iletilmez
        self.assertFalse(kw["start_if_stopped"])
        ws.tick_once("manual", "default")
        self.assertEqual(len(self.given), 1)                                   # 12 saat dolmadan yeniden gitmez
        self.assertIn("findings_advanced", [e["event"] for e in sw.tail_log(50)])
        self.assertEqual(sw.load_state(sw.paths_for("default"))["advance_sent"]["cli:r:R-1"]["n"], 1)

    def test_done_line_never_sent_and_flag_off_sends_nothing(self):
        with open(self.todo, "w") as f:
            f.write("- [x] (review cli:r:R-1) [P1] a.py:1: gerçek bulgu\n")
        self.views = [_view("cli", last_activity=time.time())]
        ws.tick_once("manual", "default")
        self.assertEqual(self.given, [])
        with open(self.todo, "w") as f:
            f.write("- [ ] (review cli:r:R-1) [P1] a.py:1: gerçek bulgu\n")
        settings.save_settings({"steward": {"enabled": "on", "mode": "act", "card_refresh": "off", "advance_findings": "off"}})
        ws.tick_once("manual", "default")
        self.assertEqual(self.given, [])

    def test_act_mode_never_sends_secret_findings(self):
        with open(self.todo, "a") as f:
            f.write("- [ ] (review cli:r:R-9) [P1] x.py:6: Veritabanı parolası kaynak koduna gömülü\n"
                    "- [ ] (review cli:r:R-8) [P1] y.py:1: DB password hardcoded\n")
        rp = sw.paths_for("rvw")
        data = rv.load_findings(rp)
        data["cli:r:R-9"] = {"project": "cli", "state": "exported", "severity": "P1", "where": "x.py:6",
                             "title": "Veritabanı parolası kaynak koduna gömülü", "exported_to": self.todo}
        data["cli:r:R-8"] = {"project": "cli", "state": "exported", "severity": "P1", "where": "y.py:1",
                             "title": "DB password hardcoded", "exported_to": self.todo}
        rv.save_findings(rp, data)
        self.views = [_view("cli", last_activity=time.time())]
        for _ in range(3):
            ws.tick_once("manual", "default")
        sent = " ".join(t for _, t, _ in self.given)
        self.assertIn("cli:r:R-1", sent)                                       # sıradan bulgu gitti
        self.assertNotIn("R-9", sent)
        self.assertNotIn("R-8", sent)
        self.assertNotIn("parola", sent.lower().replace("parola/", ""))        # başlık metni de sızmadı

    def test_observe_mode_only_logs_would(self):
        settings.save_settings({"steward": {"enabled": "on", "mode": "observe", "card_refresh": "off", "advance_findings": "on"}})
        self.views = [_view("cli", last_activity=time.time())]
        res = ws.tick_once("manual", "default")
        self.assertEqual([d["kind"] for d in res["dry"]], ["deliver_findings"])
        self.assertEqual(self.given, [])

    def test_observe_does_not_change_state_and_repeats_only_when_set_changes(self):
        settings.save_settings({"steward": {"enabled": "on", "mode": "observe", "card_refresh": "off", "advance_findings": "on"}})
        self.views = [_view("cli", last_activity=time.time())]
        ws.tick_once("manual", "default")
        st = sw.load_state(sw.paths_for("default"))
        self.assertFalse(st.get("last_directive_at"))                          # observe durum DEĞİŞTİRMEZ
        self.assertFalse(st.get("advance_sent"))
        self.assertEqual(ws.tick_once("manual", "default")["dry"], [])         # aynı küme: yinelenmez
        with open(self.todo, "a") as f:
            f.write("- [ ] (review cli:r:R-3) [P2] c.py:3: ikinci\n")
        rp = sw.paths_for("rvw")
        data = rv.load_findings(rp)
        data["cli:r:R-3"] = {"project": "cli", "state": "exported", "severity": "P2", "where": "c.py:3", "title": "ikinci",
                             "exported_to": self.todo}
        rv.save_findings(rp, data)
        self.assertEqual([d["kind"] for d in ws.tick_once("manual", "default")["dry"]], ["deliver_findings"])   # küme değişti


if __name__ == "__main__":
    unittest.main()

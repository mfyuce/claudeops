"""Uzak projede review: sahip kararı + yerel kopya (TBD#114). Gerçek uzak host/ağ/servis YOK; yerel git depoları geçici dizinde.
Çalıştırma: python3 py/tests/test_review_remote.py -v"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_steward_engine_multi import _Engine  # noqa: E402
from _no_real_review import NoRealReviewMixin  # noqa: E402
from claudeops import review_remote as rr, settings, steward as sw  # noqa: E402
from claudeops.commands import web_review as wr, web_steward as ws  # noqa: E402


def git(path, *args):
    subprocess.run(["git", "-C", path, *args], check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))


_REAL_RUN_JOB = wr.run_job


class FakeDriver:
    """review_remote_run sürücü sözleşmesi: gerçek uzak G/Ç YOK. `script`: sıradaki poll yanıtları (sonuncusu tekrarlanır)."""
    host = "ulak_31"

    def __init__(self, project="far", host="ulak_31", script=None, ready=(True, ""), start_ok=True):
        self.project, self.host, self.script, self._ready, self.start_ok = project, host, list(script or []), ready, start_ok
        self.calls = []

    def ready(self):
        return self._ready

    def cwd(self):
        return "/srv/far"

    def start(self, model, effort):
        self.calls.append(("start", model, effort))
        return {"ok": self.start_ok, "error": "" if self.start_ok else "boom"}

    def send(self, text):
        self.calls.append(("send", text))
        return {"ok": True}

    def poll(self):
        self.calls.append(("poll",))
        return self.script.pop(0) if len(self.script) > 1 else (self.script[0] if self.script else {})

    def stop(self):
        self.calls.append(("stop",))


def make_clone(root):
    """origin (bare) + yerel kopya `clone`; (origin_work, clone) yolları. origin_work'a commit atılıp clone'a çekilir."""
    bare, work, clone = (os.path.join(root, n) for n in ("bare.git", "work", "clone"))
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    subprocess.run(["git", "clone", "-q", bare, work], check=True, capture_output=True)
    with open(os.path.join(work, "a.txt"), "w") as f:
        f.write("1\n")
    git(work, "add", "a.txt")
    git(work, "commit", "-q", "-m", "c1")
    git(work, "push", "-q", "origin", "HEAD")
    subprocess.run(["git", "clone", "-q", bare, clone], check=True, capture_output=True)
    return work, clone


class PureTest(unittest.TestCase):
    def test_parse_answer(self):
        self.assertEqual(rr.parse_answer("Yerel kopya"), ("local", ""))
        self.assertEqual(rr.parse_answer("uzak"), ("remote", ""))
        self.assertEqual(rr.parse_answer("Vazgeç"), ("off", ""))
        self.assertEqual(rr.parse_answer("yerel, yol /home/x/rustrino olur"), ("local", "/home/x/rustrino"))
        self.assertEqual(rr.parse_answer("bilmiyorum"), ("", ""))

    def test_prepare_copy_updates_and_refuses_dirty(self):
        with tempfile.TemporaryDirectory() as d:
            work, clone = make_clone(d)
            with open(os.path.join(work, "a.txt"), "a") as f:
                f.write("2\n")
            git(work, "commit", "-qam", "c2")
            git(work, "push", "-q", "origin", "HEAD")
            ok, _ = rr.prepare_copy(clone)
            self.assertTrue(ok)
            self.assertEqual(open(os.path.join(clone, "a.txt")).read(), "1\n2\n")        # ileri sarıldı
            with open(os.path.join(clone, "a.txt"), "a") as f:
                f.write("yerel\n")
            ok, msg = rr.prepare_copy(clone)
            self.assertFalse(ok)
            self.assertIn("kaydedilmemiş", msg)
            self.assertEqual(open(os.path.join(clone, "a.txt")).read(), "1\n2\nyerel\n")  # yerel değişiklik ezilmedi
            self.assertFalse(rr.prepare_copy(os.path.join(d, "yok"))[0])

    def test_prepare_copy_stops_on_divergence(self):
        with tempfile.TemporaryDirectory() as d:
            work, clone = make_clone(d)
            with open(os.path.join(work, "a.txt"), "a") as f:
                f.write("uzak\n")
            git(work, "commit", "-qam", "remote")
            git(work, "push", "-q", "origin", "HEAD")
            with open(os.path.join(clone, "b.txt"), "w") as f:
                f.write("yerel\n")
            git(clone, "add", "b.txt")
            git(clone, "commit", "-q", "-m", "local")
            ok, msg = rr.prepare_copy(clone)
            self.assertFalse(ok)
            self.assertIn("ff-only", msg)


class RemoteFlowTest(NoRealReviewMixin, _Engine):
    def setUp(self):
        super().setUp()
        self.settings()
        settings.save_settings({"stewards": {"rev": {"enabled": "on", "mode": "act", "role": "reviewer"}}})
        os.makedirs(sw.paths_for("rev").root, exist_ok=True)
        wr._JOBS.clear()
        wr._COPY_FAIL.clear()
        self.addCleanup(wr._JOBS.clear)
        self.runs, self.notified = [], []

        def fake_run(paths, cfg, project, cwd, target, **kw):
            self.runs.append((project, cwd))
            return {"ok": True, "key": f"{project}|{target.key}"}
        for p in (mock.patch.object(wr, "run_job", fake_run),
                  mock.patch.object(wr, "current_targets", lambda cfg: [wr.rv.ReviewTarget("evren", "m1", "m1")]),
                  mock.patch.object(wr, "project_cwd", lambda n: ""),
                  mock.patch.object(wr, "_NOTIFY_FN", lambda sid, q: self.notified.append((sid, q.id)))):
            p.start()
            self.addCleanup(p.stop)
        with mock.patch.object(sw.hosts_mod, "get_host", lambda h: {"name": h} if h == "ulak_31" else None):
            sw.upsert_project("far", phase="planned", host="ulak_31")

    def cfg(self):
        return ws.steward_config("rev")

    def test_unknown_choice_blocks_review_and_asks_the_owner_once(self):
        self.assertIn("not reviewed", wr.remote_block_reason("far"))
        self.assertFalse(wr.pool_action(self.cfg(), "add", "far")["ok"])
        self.assertEqual(wr.ask_remote_choice(self.cfg(), 1000.0), "far")
        qs = [q for q in sw.load_questions() if q.source == rr.ASK_SOURCE]
        self.assertEqual((len(qs), qs[0].options, self.notified), (1, rr.OPTIONS, [("default", qs[0].id)]))
        self.assertEqual(sw.load_projects()["far"].review_where, "ask")
        self.assertIsNone(wr.ask_remote_choice(self.cfg(), 1001.0))                # açık soru varken ikinci soru yok

    def test_local_answer_enables_the_copy_and_runs_there(self):
        with tempfile.TemporaryDirectory() as d:
            _work, clone = make_clone(d)
            wr.ask_remote_choice(self.cfg(), 1000.0)
            q = next(x for x in sw.load_questions() if x.source == rr.ASK_SOURCE)
            sw.answer_question(q.id, f"1 {clone}")                                  # "Yerel kopya" + yol
            pj = sw.load_projects()["far"]
            self.assertEqual((pj.review_where, pj.local_path), ("local", clone))
            self.assertTrue(sw.find_question(q.id).delivered_at)                     # cevap oturuma iletilmez
            self.assertEqual(wr.remote_block_reason("far"), "")
            self.assertIn("far", wr.local_owned_names())
            res = wr.manual_run(self.cfg(), "far")
            self.assertTrue(res["ok"], res)
            self.assertEqual(self.runs, [("far", clone)])

    def test_dirty_copy_blocks_manual_run_and_tick_logs_once(self):
        with tempfile.TemporaryDirectory() as d:
            _work, clone = make_clone(d)
            sw.upsert_project("far", review_where="local", local_path=clone)
            with open(os.path.join(clone, "a.txt"), "a") as f:
                f.write("kirli\n")
            r = wr.manual_run(self.cfg(), "far")
            self.assertFalse(r["ok"])
            self.assertIn("kaydedilmemiş", r["error"])
            for i in range(3):
                res = wr.review_tick(self.cfg(), now=2000.0 + i)
            self.assertEqual(self.runs, [])
            self.assertTrue(any(a["kind"] == "copy_not_ready" for a in res["actions"]))
            self.assertEqual(sum(1 for e in sw.tail_log(50, "rev") if e["event"] == "review_copy_not_ready"), 2)   # manual_run 1 + tick 1 (yineleme susar)

    def test_off_answer_stops_asking_and_remote_is_recorded_only(self):
        wr.ask_remote_choice(self.cfg(), 1000.0)
        q = next(x for x in sw.load_questions() if x.source == rr.ASK_SOURCE)
        sw.answer_question(q.id, "Vazgeç")
        self.assertEqual(sw.load_projects()["far"].review_where, "off")
        self.assertIsNone(wr.ask_remote_choice(self.cfg(), 1000.0 + 10 * 86400))
        sw.upsert_project("far", review_where="remote")
        self.assertEqual(wr.remote_block_reason("far"), "")                        # sürücü web_steward import'unda bağlı (TBD#117 ek 3 c)
        with mock.patch.object(wr, "_REMOTE_FN", None):
            self.assertIn("not wired", wr.remote_block_reason("far"))

    def test_remote_mode_tick_starts_job_with_empty_cwd_when_ready(self):
        sw.upsert_project("far", review_where="remote")
        self.assertIn("far", wr.local_owned_names())
        drv = FakeDriver()
        with mock.patch.object(wr, "_REMOTE_FN", lambda p, h: drv):
            res = wr.review_tick(self.cfg(), now=5000.0)
        self.assertEqual(self.runs, [("far", "")], res)

    def test_remote_mode_tick_waits_when_gates_say_no(self):
        sw.upsert_project("far", review_where="remote")
        drv = FakeDriver(ready=(False, "target denied: remote actions are disabled"))
        with mock.patch.object(wr, "_REMOTE_FN", lambda p, h: drv):
            res = wr.review_tick(self.cfg(), now=5000.0)
        self.assertEqual(self.runs, [])
        self.assertTrue(any(a["kind"] == "remote_not_ready" for a in res["actions"]), res)

    def test_remote_mode_accepts_only_evren_targets(self):
        sw.upsert_project("far", review_where="remote")
        drv = FakeDriver()
        both = [wr.rv.ReviewTarget("evren", "m1", "m1"), wr.rv.ReviewTarget("claude", "claude-x", "claude-x")]
        with mock.patch.object(wr, "_REMOTE_FN", lambda p, h: drv), mock.patch.object(wr, "current_targets", lambda cfg: both):
            r = wr.manual_run(self.cfg(), "far", mode="claude", model="claude-x")
        self.assertFalse(r["ok"])
        self.assertIn("evren", r["error"])

    def test_remote_run_job_end_to_end_writes_report_and_stops_session(self):
        sw.upsert_project("far", review_where="remote")
        report = "## R-1 | P2 | a.py:3 | Gerçek kusur\ngövde"
        user = wr.rv.build_review_prompt("far", "/srv/far", "tr")
        drv = FakeDriver(script=[{"running": True, "busy": False, "user": "", "assistant": ""},       # gönderimden önceki anlık görüntü
                                 {"running": True, "busy": True, "user": user, "assistant": "yarım"},
                                 {"running": True, "busy": False, "user": user, "assistant": report}])
        target = wr.rv.ReviewTarget("evren", "m1", "m1", "low")
        paths = sw.paths_for("rev")
        with mock.patch.object(wr, "_REMOTE_FN", lambda p, h: drv), \
                mock.patch.object(wr.rrun, "POLL_SECONDS", 0.0), mock.patch.object(wr.rrun, "MIN_WAIT_SECONDS", 0.0), \
                mock.patch.object(wr.rrun.time, "sleep", lambda s: None):
            res = _REAL_RUN_JOB(paths, self.cfg(), "far", "", target, lang="tr")
            self.assertTrue(res["ok"], res)
            res["thread"].join(30)
        hist = wr.rv.load_history(paths)["pairs"]
        rec = next(iter(hist.values()))
        self.assertEqual(rec["status"], "done", rec)
        with open(rec["file"], encoding="utf-8") as f:
            self.assertIn("R-1 | P2", f.read())
        kinds = [c[0] for c in drv.calls]
        self.assertEqual(kinds[0], "start")
        self.assertIn("send", kinds)
        self.assertEqual(kinds[-1], "stop")
        self.assertEqual(drv.calls[0][1:], ("m1", "low"))
        self.assertTrue(wr.rv.load_findings(paths))                                 # bulgu kaydedildi (state=new)

    def test_unrecognized_answer_reasks_only_after_retry_window(self):
        t0 = time.time()
        wr.ask_remote_choice(self.cfg(), t0)
        q = next(x for x in sw.load_questions() if x.source == rr.ASK_SOURCE)
        sw.answer_question(q.id, "bilmiyorum")
        self.assertEqual(sw.load_projects()["far"].review_where, "ask")
        self.assertIsNone(wr.ask_remote_choice(self.cfg(), t0 + 3600))
        self.assertEqual(wr.ask_remote_choice(self.cfg(), t0 + wr.ASK_RETRY_SECONDS + 5), "far")

    def test_invalid_values_are_ignored_by_upsert(self):
        sw.upsert_project("far", review_where="bogus", local_path="relative/path")
        pj = sw.load_projects()["far"]
        self.assertEqual((pj.review_where, pj.local_path), ("", ""))


if __name__ == "__main__":
    unittest.main()

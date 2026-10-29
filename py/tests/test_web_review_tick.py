"""review_tick planlayıcı testleri: sahte run_job (gerçek Popen/agy/Evren/ağ YOK), geçici dizinler.
Çalıştırma: python3 -m unittest discover -s py/tests"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_steward_engine_multi import _Engine  # noqa: E402
from _no_real_review import NoRealReviewMixin  # noqa: E402
from claudeops import review as rv, settings, steward as sw  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402

T1 = rv.ReviewTarget("evren", "m1", "m1")
T2 = rv.ReviewTarget("agy", "m2", "m2")
NOW = 1_800_000_000.0


class _Tick(NoRealReviewMixin, _Engine):
    def setUp(self):
        super().setUp()
        self.settings()
        settings.save_settings({"stewards": {"rev": {"enabled": "on", "mode": "act", "role": "reviewer",
                                                     "review_min_gap_minutes": "0"}}})
        os.makedirs(sw.paths_for("rev").root, exist_ok=True)
        wr._RECOVERED.clear()
        wr._JOBS.clear()
        self.started = []
        self.hold = False
        self.cwds = {}
        self.targets = [T1, T2]
        ps = [mock.patch.object(wr, "run_job", self.fake_run), mock.patch.object(wr, "current_targets", lambda cfg: self.targets),
              mock.patch.object(wr, "project_cwd", lambda n: self.cwds.get(n, "")),
              mock.patch.object(wr, "_REVIEW_BACKGROUND", False)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(wr._JOBS.clear)

    def fake_run(self, paths, cfg, project, cwd, target, **kw):
        self.started.append((project, target.key))
        if self.hold:
            j = wr._Job(rv.pair_key(project, target))
            j.sid = paths.sid
            j.proc = mock.Mock(pid=0, poll=lambda: None)
            wr._JOBS[j.key] = j
            rv.update_pair(paths, project, target, status="running", started_at=NOW)
        else:
            rv.update_pair(paths, project, target, status="done", started_at=NOW, finished_at=NOW)
        return {"ok": True, "key": rv.pair_key(project, target)}

    def own(self, *names):
        for n in names:
            sw.upsert_project(n, phase="planned")
            self.cwds[n] = self.dir.name

    def cfg(self):
        return settings.steward_config("rev")


class TestReviewerSmalls(_Tick):
    """TODO 2026-10-28 (21) reviewer küçükleri: rapor 0600, cfg.lang isteme ulaşır."""

    def test_report_file_is_private(self):
        path = os.path.join(self.dir.name, "r", "x.md")
        wr._write_report(path, "## R-1 | P1 | a.py:1 | x\n")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_cfg_lang_reaches_run_job(self):
        self.own("a")
        seen = {}
        orig = self.fake_run

        def spy(paths, cfg, project, cwd, target, **kw):
            seen.update(kw)
            return orig(paths, cfg, project, cwd, target, **kw)
        settings.save_settings({"stewards": {"rev": {"lang": "en"}}})
        with mock.patch.object(wr, "run_job", spy):
            wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(seen.get("lang"), "en")


class TestTick(_Tick):
    def test_pool_autofills_and_starts_one_job_at_a_time(self):
        self.own("a", "b")
        self.hold = True
        r = wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(r["started"], 1)
        self.assertEqual(sorted(rv.pool_enabled(rv.load_pool(sw.paths_for("rev")))), ["a", "b"])   # yeni proje otomatik girer
        r2 = wr.review_tick(self.cfg(), now=NOW + 5)
        self.assertEqual(r2["started"], 0)
        self.assertTrue(r2.get("busy"))
        self.assertEqual(len(self.started), 1)

    def test_remote_project_skipped(self):
        self.own("a")
        with mock.patch.object(sw.hosts_mod, "get_host", lambda h: {"name": h} if h == "ulak_31" else None):   # hosts.json'a bağımlı olma
            sw.upsert_project("far", phase="planned", host="ulak_31")
        self.cwds["far"] = self.dir.name
        wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(rv.pool_enabled(rv.load_pool(sw.paths_for("rev"))), ["a"])

    def test_disabled_identity_starts_nothing_and_cancels(self):
        self.own("a")
        self.hold = True
        wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(len(wr.running_keys("rev")), 1)
        settings.save_settings({"stewards": {"rev": {"enabled": "off"}}})
        with mock.patch.object(wr, "cancel_key", return_value=True) as ck:
            r = wr.review_tick(self.cfg(), now=NOW + 1)
        self.assertEqual(r["started"], 0)
        ck.assert_called_once()
        self.started.clear()
        self.hold = False
        wr._JOBS.clear()
        wr.review_tick(self.cfg(), now=NOW + 2)
        self.assertEqual(self.started, [])

    def test_disabled_project_cancels_running_job(self):
        self.own("a")
        self.hold = True
        wr.review_tick(self.cfg(), now=NOW)
        p = sw.paths_for("rev")
        pool = rv.load_pool(p)
        pool["projects"]["a"]["enabled"] = False
        rv.save_pool(p, pool)
        with mock.patch.object(wr, "cancel_key", return_value=True) as ck:
            r = wr.review_tick(self.cfg(), now=NOW + 1)
        ck.assert_called_once_with("a|evren/m1")
        self.assertIn("cancel", [a["kind"] for a in r["actions"]])

    def test_readded_project_resumes_skipping_done_pairs(self):
        self.own("a")
        wr.review_tick(self.cfg(), now=NOW)                  # T1 done
        self.assertEqual(self.started, [("a", "evren/m1")])
        wr.review_tick(self.cfg(), now=NOW + 1)               # T2 sonraki
        self.assertEqual(self.started[-1], ("a", "agy/m2"))
        self.started.clear()
        wr.review_tick(self.cfg(), now=NOW + 2)               # ikisi de taze: iş yok
        self.assertEqual(self.started, [])
        p = sw.paths_for("rev")
        rv.update_pair(p, "a", T2, status="partial", finished_at=NOW)   # yarım kalan çift
        wr.review_tick(self.cfg(), now=NOW + 3)
        self.assertEqual(self.started, [("a", "agy/m2")])    # tamamlanan T1 atlandı, partial önce

    def test_drain_finishes_running_job_but_starts_nothing_new(self):
        # TODO 2026-10-28 (21): reviewer'da "bitir, yeni başlatma" kipi yoktu (restart öncesi boşaltılamıyordu)
        self.own("a", "b")
        self.hold = True
        self.assertEqual(wr.review_tick(self.cfg(), now=NOW)["started"], 1)
        settings.save_settings({"stewards": {"rev": {"drain": "on"}}})
        r = wr.review_tick(self.cfg(), now=NOW + 5)
        self.assertTrue(r.get("busy"))                                       # koşan iş iptal EDİLMEZ
        self.assertEqual(len(wr.running_keys()), 1)
        wr._JOBS.clear()                                                     # iş bitti
        r = wr.review_tick(self.cfg(), now=NOW + 10)
        self.assertEqual((r["started"], r.get("draining")), (0, True))
        self.assertEqual(len(self.started), 1)
        settings.save_settings({"stewards": {"rev": {"drain": "off"}}})
        self.hold = False
        self.assertEqual(wr.review_tick(self.cfg(), now=NOW + 15)["started"], 1)    # drain kapanınca sürer

    def test_min_gap_blocks_start(self):
        self.own("a")
        settings.save_settings({"stewards": {"rev": {"review_min_gap_minutes": "10"}}})
        wr.review_tick(self.cfg(), now=NOW)
        r = wr.review_tick(self.cfg(), now=NOW + 60)
        self.assertEqual(r["started"], 0)
        self.assertIn("waiting", r)
        wr.review_tick(self.cfg(), now=NOW + 700)
        self.assertEqual(len(self.started), 2)

    def test_recover_once_and_missing_cwd_skipped_and_no_targets(self):
        self.own("a", "b")
        del self.cwds["a"]
        p = sw.paths_for("rev")
        rv.update_pair(p, "z", T1, status="running", started_at=1.0)
        r = wr.review_tick(self.cfg(), now=NOW)
        self.assertEqual(rv.load_history(p)["pairs"]["z|evren/m1"]["status"], "partial")
        self.assertEqual(self.started, [("b", "evren/m1")])      # a'nın klasörü yok: atlandı
        self.assertIn("recover", [a["kind"] for a in r["actions"]])
        rv.update_pair(p, "q", T1, status="running", started_at=1.0)
        wr.review_tick(self.cfg(), now=NOW + 1)                  # ikinci tick recover ETMEZ
        self.assertEqual(rv.load_history(p)["pairs"]["q|evren/m1"]["status"], "running")
        self.targets = []
        self.assertEqual(wr.review_tick(self.cfg(), now=NOW + 2)["started"], 0)


class TestModelsFailure(unittest.TestCase):
    def test_current_targets_swallows_errors(self):
        with mock.patch.object(wr, "available_models", side_effect=RuntimeError("x")):
            self.assertEqual(wr.current_targets(sw.Config()), [])


if __name__ == "__main__":
    unittest.main()

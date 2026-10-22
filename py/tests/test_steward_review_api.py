"""reviewer yüzeyi (adım 6): GET review/state|file|findings, POST review/pool|run|cancel, CLI ayrıştırma.
Gerçek servis/agy/Evren/ağ/Popen YOK. Çalıştırma: python3 -m unittest discover -s py/tests"""
import argparse
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_steward_engine_multi import _Engine  # noqa: E402
from claudeops import review as rv, settings, steward as sw  # noqa: E402
from claudeops.commands import steward as cli, web_review as wr, web_steward as ws  # noqa: E402

T1 = rv.ReviewTarget("evren", "m1", "m1")
T2 = rv.ReviewTarget("agy", "m2", "m2")


class _Api(_Engine):
    def setUp(self):
        super().setUp()
        self.settings()
        settings.save_settings({"stewards": {"rev": {"enabled": "on", "mode": "act", "role": "reviewer"}}})
        os.makedirs(sw.paths_for("rev").root, exist_ok=True)
        wr._JOBS.clear()
        self.addCleanup(wr._JOBS.clear)
        self.runs = []

        def fake_run(paths, cfg, project, cwd, target, **kw):
            self.runs.append((project, target.key))
            return {"ok": True, "key": rv.pair_key(project, target)}

        for p in (mock.patch.object(wr, "current_targets", lambda cfg: [T1, T2]),
                  mock.patch.object(wr, "run_job", fake_run),
                  mock.patch.object(wr, "project_cwd", lambda n: self.dir.name if n in ("a", "b") else "")):
            p.start()
            self.addCleanup(p.stop)
        sw.upsert_project("a", phase="planned")
        sw.upsert_project("far", phase="planned", host="ulak_31")


class TestPool(_Api):
    def test_pool_add_disable_enable_remove(self):
        post = lambda a, p: ws.http_post("/api/steward/review/pool", {"steward": "rev", "action": a, "project": p})
        self.assertTrue(post("add", "b")["ok"])
        self.assertFalse(post("add", "nope")["ok"])                      # bilinmeyen proje
        self.assertFalse(post("add", "far")["ok"])                       # uzak proje
        self.assertTrue(post("disable", "b")["ok"])
        self.assertEqual(rv.pool_enabled(rv.load_pool(sw.paths_for("rev"))), [])
        self.assertTrue(post("enable", "b")["ok"])
        self.assertEqual(rv.pool_enabled(rv.load_pool(sw.paths_for("rev"))), ["b"])
        self.assertTrue(post("remove", "b")["ok"])
        self.assertNotIn("b", rv.load_pool(sw.paths_for("rev"))["projects"])
        self.assertFalse(post("remove", "b")["ok"])
        self.assertFalse(post("explode", "a")["ok"])

    def test_remove_of_auto_project_is_not_reenabled_by_sync(self):
        wr.sync_pool(sw.paths_for("rev"), 1.0, ["a"])
        self.assertTrue(ws.http_post("/api/steward/review/pool", {"steward": "rev", "action": "remove", "project": "a"})["ok"])
        wr.sync_pool(sw.paths_for("rev"), 2.0, ["a"])
        self.assertEqual(rv.pool_enabled(rv.load_pool(sw.paths_for("rev"))), [])

    def test_list_row_carries_role_only_for_reviewer(self):
        ws.invalidate_summary()
        rows = {r["id"]: r for r in ws.stewards_summary(running_names=set())}
        self.assertEqual(rows["rev"].get("role"), "reviewer")
        self.assertNotIn("role", rows["default"])

    def test_non_reviewer_and_unknown_steward_rejected(self):
        r = ws.http_post("/api/steward/review/pool", {"action": "add", "project": "a"})        # default
        self.assertFalse(r["ok"])
        self.assertIn("not a reviewer", r["error"])
        self.assertEqual(ws.http_post("/api/steward/review/run", {"steward": "zzz", "project": "a"})["error"], "unknown steward")

    def test_brain_actor_rejected_everywhere(self):
        for path, body in (("pool", {"action": "add", "project": "a"}), ("run", {"project": "a"}), ("cancel", {})):
            r = ws.http_post("/api/steward/review/" + path, dict(body, steward="rev", actor="brain"))
            self.assertFalse(r["ok"], path)
            self.assertIn("brain cannot", r["error"])
        self.assertEqual(self.runs, [])


class TestRunCancel(_Api):
    def test_manual_run_validates_and_starts(self):
        post = lambda b: ws.http_post("/api/steward/review/run", dict(b, steward="rev"))
        self.assertEqual(post({"project": "a", "mode": "evren", "model": "m1"})["key"], "a|evren/m1")
        self.assertEqual(post({"project": "a"})["key"], "a|evren/m1")                  # sıradaki hedef
        self.assertFalse(post({"project": "a", "mode": "evren", "model": "bilinmeyen"})["ok"])
        self.assertFalse(post({"project": "a", "mode": "x", "model": "m1"})["ok"])
        self.assertFalse(post({"project": "far"})["ok"])
        self.assertFalse(post({"project": "zzz"})["ok"])

    def test_manual_run_refused_when_disabled_or_busy(self):
        j = wr._Job("a|evren/m1")
        j.sid = "rev"
        wr._JOBS[j.key] = j
        r = ws.http_post("/api/steward/review/run", {"steward": "rev", "project": "a"})
        self.assertTrue(r.get("busy"))
        wr._JOBS.clear()
        settings.save_settings({"stewards": {"rev": {"enabled": "off"}}})
        self.assertFalse(ws.http_post("/api/steward/review/run", {"steward": "rev", "project": "a"})["ok"])
        self.assertEqual(self.runs, [])

    def test_cancel_calls_cancel_key(self):
        j = wr._Job("a|evren/m1")
        j.sid = "rev"
        wr._JOBS[j.key] = j
        with mock.patch.object(wr, "cancel_key", return_value=True):
            r = ws.http_post("/api/steward/review/cancel", {"steward": "rev", "project": "a"})
            self.assertEqual(r["cancelled"], ["a|evren/m1"])
            self.assertEqual(ws.http_post("/api/steward/review/cancel", {"steward": "rev", "project": "b"})["cancelled"], [])


class TestReads(_Api):
    def test_state_findings_and_file(self):
        p = sw.paths_for("rev")
        wr.sync_pool(p, 5.0, ["a"])
        rv.update_pair(p, "a", T1, status="done", started_at=1.0, finished_at=2.0)
        f = rv.review_path(p.reviews, "a", T1, 1_700_000_000)
        os.makedirs(os.path.dirname(f))
        with open(f, "w") as fh:
            fh.write("## R-1 | P2 | x.py:1 | Baslik\ngovde\n")
        rv.add_findings(p, "a", f, rv.parse_findings("## R-1 | P2 | x.py:1 | Baslik\ngovde\n"))
        st = ws.http_get("/api/steward/review/state", {"steward": ["rev"]})
        self.assertTrue(st["ok"])
        self.assertEqual([t["key"] for t in st["targets"]], ["evren/m1", "agy/m2"])
        row = st["pool"][0]
        self.assertEqual(row["project"], "a")
        self.assertFalse(row["complete"])
        self.assertEqual(row["pairs"]["evren/m1"]["status"], "done")
        fd = ws.http_get("/api/steward/review/findings", {"steward": ["rev"], "project": ["a"]})
        self.assertEqual(len(fd["findings"]), 1)
        self.assertEqual(ws.http_get("/api/steward/review/findings", {"steward": ["rev"], "state": ["approved"]})["findings"], [])
        rel = os.path.relpath(f, p.reviews)
        ok = ws.http_get("/api/steward/review/file", {"steward": ["rev"], "path": [rel]})
        self.assertIn("Baslik", ok["text"])
        self.assertTrue(ws.http_get("/api/steward/review/file", {"steward": ["rev"], "path": [f]})["ok"])   # kendi mutlak yolu

    def test_file_path_escape_rejected(self):
        p = sw.paths_for("rev")
        os.makedirs(p.reviews, exist_ok=True)
        secret = os.path.join(p.root, "findings.json")
        with open(secret, "w") as fh:
            fh.write("{}")
        os.symlink(secret, os.path.join(p.reviews, "link.md"))
        for bad in ("../findings.json", "a/../../findings.json", secret, "/etc/passwd", "link.md", "", "x\x00y"):
            r = ws.http_get("/api/steward/review/file", {"steward": ["rev"], "path": [bad]})
            self.assertFalse(r["ok"], bad)

    def test_reads_need_reviewer(self):
        self.assertFalse(ws.http_get("/api/steward/review/state", {})["ok"])


class TestCli(_Api):
    def setUp(self):
        super().setUp()
        self.calls = []

        def fake_api(port, method, path, body=None):
            self.calls.append((method, path, body))
            return {"ok": True, "key": "k", "cancelled": [], "findings": [], "runs": [], "pool": [], "targets": [], "running": []}

        p = mock.patch.object(cli.mcp_queue, "_api", fake_api)
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, *argv):
        ap = argparse.ArgumentParser()
        cli.register(ap.add_subparsers())
        args = ap.parse_args(["steward", "-s", "rev", *argv])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = args.func(args)
        return rc, out.getvalue()

    def test_parsing_maps_to_api(self):
        self.run_cli("review", "pool", "add", "a")
        self.run_cli("review", "pool", "rm", "a")
        self.run_cli("review", "pool", "on", "a")
        self.run_cli("review", "pool", "off", "a")
        self.run_cli("review", "run", "a", "evren/glm/4.6")
        self.run_cli("review", "run", "a")
        self.run_cli("review", "cancel", "a")
        self.assertEqual([c[2]["action"] for c in self.calls[:4]], ["add", "remove", "enable", "disable"])
        self.assertEqual(self.calls[4][2], {"project": "a", "mode": "evren", "model": "glm/4.6", "steward": "rev"})
        self.assertEqual(self.calls[5][2]["mode"], "")
        self.assertEqual(self.calls[6][1], "/api/steward/review/cancel")

    def test_reads_status_history_findings(self):
        for sub in (("review",), ("review", "status"), ("review", "history"), ("review", "findings", "--project", "a", "--state", "new")):
            rc, _ = self.run_cli(*sub)
            self.assertEqual(rc, 0, sub)
        self.assertIn("project=a", self.calls[-1][1])
        self.assertIn("steward=rev", self.calls[-1][1])
        self.assertEqual(self.run_cli("review", "run", "a", "evren")[0], 1)         # biçim hatası
        with self.assertRaises(SystemExit):
            self.run_cli("review", "pool", "zap", "a")


if __name__ == "__main__":
    unittest.main()

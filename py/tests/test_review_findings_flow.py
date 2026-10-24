"""reviewer bulgu akışı (adım 7): otomatik bulgu kaydı, doğrulama direktifi (sahibin oturumu, insan aktörü),
STEWARD-REVIEW-VERDICT okuma (yalnız sahibin oturumu, yalnız gerçek satır), sahip onayı, TODO/TBD dışa aktarımı.
Gerçek tmux/oturum/Popen/ağ YOK: `_collect_views` sahte görünüm, `_give_directive` kayıt tutar.
Çalıştırma: python3 -m unittest discover -s py/tests"""
import argparse
import contextlib
import io
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_steward_engine_multi import _Engine, _view  # noqa: E402
from _no_real_review import NoRealReviewMixin  # noqa: E402
from claudeops import review as rv, settings, steward as sw  # noqa: E402
from claudeops.commands import steward as cli, web_review as wr, web_steward as ws  # noqa: E402

T1 = rv.ReviewTarget("evren", "m1", "m1")
REVIEW_MD = ("## R-1 | P1 | x.py:10 | Birinci\ngovde 1\n\n## R-2 | P2 | y.py:3 | Ikinci\ngovde 2\n\n"
             "## R-3 | P3 | z.py:7 | Ucuncu\ngovde 3\n")


class FakeProc:
    def __init__(self, argv, out="", **kw):
        self.argv, self.out, self.pid, self.returncode = argv, out, 4242, None

    def communicate(self, timeout=None):
        self.returncode = 0
        return self.out, ""

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0


class _Flow(NoRealReviewMixin, _Engine):
    def setUp(self):
        super().setUp()
        self.settings()
        settings.save_settings({"stewards": {"rev": {"enabled": "on", "mode": "act", "role": "reviewer"}}})
        os.makedirs(sw.paths_for("rev").root, exist_ok=True)
        self.proj_dir = os.path.join(self.dir.name, "proj_a")
        os.makedirs(self.proj_dir)
        sw.upsert_project("a", phase="planned")                  # sahibi: default
        sw.upsert_project("k", paths="kitap", phase="planned")   # sahibi: kitap
        with mock.patch.object(sw.hosts_mod, "get_host", lambda h: {"name": h} if h == "ulak_31" else None):   # hosts.json'a bağımlı olma
            sw.upsert_project("far", phase="planned", host="ulak_31")
        self.sent = []

        def give(project, text, **kw):
            self.sent.append((project.name, kw.get("session_name"), text, kw.get("start_if_stopped"), kw.get("actor"),
                              kw.get("cfg").sid))
            return {"ok": True, "name": kw.get("session_name")}

        for p in (mock.patch.object(ws, "_give_directive", give),
                  mock.patch.object(wr, "project_cwd", lambda n: self.proj_dir if n == "a" else ""),
                  mock.patch.object(wr, "current_targets", lambda cfg: [T1]),
                  # tick bir review başlatmaya kalkarsa gerçek Popen OLMASIN
                  mock.patch.object(wr, "start_job", lambda *a, **k: {"ok": False, "error": "test: no runs"})):
            p.start()
            self.addCleanup(p.stop)
        wr._JOBS.clear()
        self.addCleanup(wr._JOBS.clear)
        self.p = sw.paths_for("rev")

    def seed(self, md=REVIEW_MD, proj="a"):
        f = rv.review_path(self.p.reviews, proj, T1, 1_700_000_000)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w") as fh:
            fh.write(md)
        return rv.add_findings(self.p, proj, f, rv.parse_findings(md))

    def post(self, path, **body):
        return ws.http_post("/api/steward/review/" + path, dict(body, steward="rev"))

    def findings(self):
        return rv.load_findings(self.p)

    def tick(self):
        return wr.review_tick(ws.steward_config("rev"), now=5_000.0)


class TestAutoFindings(_Flow):
    def test_done_review_records_findings_as_new(self):
        res = wr.run_job(self.p, NS(review_timeout_minutes=1), "a", self.proj_dir, T1,
                         popen=lambda argv, **k: FakeProc(argv, out='{"answer": %s}' % __import__("json").dumps(REVIEW_MD)),
                         ucli_bin="/f/ucli", api_key="k", endpoint_fn=lambda: "e", supports_flag=lambda b, f: False)
        res["thread"].join(10)
        data = self.findings()
        self.assertEqual(sorted(v["ref"] for v in data.values()), ["R-1", "R-2", "R-3"])
        self.assertTrue(all(v["state"] == "new" and v["project"] == "a" for v in data.values()))


class TestScanVerdicts(unittest.TestCase):
    def test_only_real_line_start(self):
        text = ("Özet: `STEWARD-REVIEW-VERDICT: a:x:R-9 verified prose` satırı örnektir.\n"
                "```\nSTEWARD-REVIEW-VERDICT: a:x:R-1 verified kod bloğu\n```\n"
                "> STEWARD-REVIEW-VERDICT: a:x:R-2 verified alıntı\n"
                "STEWARD-REVIEW-VERDICT: <fid> verified <gerekçe>\n"
                "STEWARD-REVIEW-VERDICT: a:x:R-4 verified <gerekçe>\n"
                "STEWARD-REVIEW-VERDICT: a:x:R-5 verified|refuted|unclear neden\n"
                "- STEWARD-REVIEW-VERDICT: a:x:R-6 verified madde imi\n"
                "  STEWARD-REVIEW-VERDICT: a:x:R-3 refuted kodda yok\n"
                "STEWARD-REVIEW-VERDICT: a:x:R-7 unclear\n")
        self.assertEqual(rv.scan_verdicts(text), [("a:x:R-3", "refuted", "kodda yok"), ("a:x:R-7", "unclear", "")])


class TestVerify(_Flow):
    def test_verify_sends_via_owner_human_directive_and_marks(self):
        fids = self.seed()
        self.views = [_view("a", last_assistant="eski cevap")]
        r = self.post("verify", project="a")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["owner"], "default")
        self.assertEqual(len(self.sent), 1)
        name, session, text, start, actor, owner_sid = self.sent[0]
        self.assertEqual((name, session, start, actor, owner_sid), ("a", "a", False, "", "default"))
        self.assertIn(rv.VERDICT_MARK, text)
        self.assertIn("Sonnet", text)
        for f in fids:
            self.assertIn(f, text)
        self.assertTrue(all(v["state"] == "verify_sent" for v in self.findings().values()))

    def test_closed_project_is_explicit_error_and_nothing_sent(self):
        self.seed()
        self.views = [_view("a", running=False)]
        r = self.post("verify", project="a")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "not_running")
        self.assertEqual(self.sent, [])
        self.assertTrue(all(v["state"] == "new" for v in self.findings().values()))

    def test_busy_or_subagent_defers(self):
        self.seed()
        for kw in ({"busy": True}, {"subagent_active": True}):
            self.views = [_view("a", **kw)]
            r = self.post("verify", project="a")
            self.assertEqual(r.get("code"), "session_busy", kw)
        self.assertEqual(self.sent, [])

    def test_remote_and_unknown_projects_rejected(self):
        self.seed(proj="far")
        self.assertFalse(self.post("verify", project="far")["ok"])
        self.assertFalse(self.post("verify", project="zzz")["ok"])
        self.assertEqual(self.sent, [])


class TestVerdicts(_Flow):
    def setUp(self):
        super().setUp()
        self.fids = self.seed()
        self.views = [_view("a", last_assistant="eski cevap")]
        self.assertTrue(self.post("verify", project="a")["ok"])

    def test_verdict_from_owner_session_applied_once(self):
        f1, f2, f3 = self.fids
        self.views = [_view("a", last_assistant=(
            "Doğrulama bitti.\n```\nSTEWARD-REVIEW-VERDICT: %s refuted örnek\n```\n"
            "STEWARD-REVIEW-VERDICT: %s verified x.py:10 gerçekten taşıyor\n"
            "STEWARD-REVIEW-VERDICT: %s refuted y.py:3 korunuyor\n"
            "STEWARD-REVIEW-VERDICT: bilinmeyen:fid:R-1 verified\n") % (f1, f1, f2))]
        res = self.tick()
        self.assertIn({"kind": "verdicts", "findings": [f1, f2]}, res["actions"])
        d = self.findings()
        self.assertEqual((d[f1]["state"], d[f2]["state"], d[f3]["state"]), ("verified", "refuted", "verify_sent"))
        self.assertEqual(d[f1]["verdict"], "x.py:10 gerçekten taşıyor")
        self.assertEqual(d[f1]["verdict_session"], "a")
        # aynı transkript yeniden: hiçbir şey değişmez
        res2 = self.tick()
        self.assertFalse(any(a["kind"] == "verdicts" for a in res2["actions"]))

    def test_code_block_example_not_counted(self):
        f1 = self.fids[0]
        self.views = [_view("a", last_assistant="```\nSTEWARD-REVIEW-VERDICT: %s verified örnek\n```\n" % f1)]
        self.tick()
        self.assertEqual(self.findings()[f1]["state"], "verify_sent")

    def test_other_session_source_rejected(self):
        f1 = self.fids[0]
        line = "STEWARD-REVIEW-VERDICT: %s verified bence\n" % f1
        # başka kimliğin projesi (kitap/k) ve kayıtsız ad hoc oturum: sahibin oturumu değil
        self.views = [_view("a", last_assistant="henüz yok"), _view("k", last_assistant=line),
                      _view("adhoc", last_assistant=line)]
        self.tick()
        self.assertEqual(self.findings()[f1]["state"], "verify_sent")

    def test_baseline_text_not_reprocessed(self):
        # doğrulama gönderilirken görülen eski yanıt (ör. önceki doğrulamadan kalma satır) yeniden işlenmez
        f1 = self.fids[0]
        old = "STEWARD-REVIEW-VERDICT: %s verified eski\n" % f1
        rv.mark_verify_sent(self.p, [f1], "a", rv.text_hash(old), 1.0)
        d = self.findings()
        d[f1]["state"] = "verify_sent"
        rv.save_findings(self.p, d)
        self.views = [_view("a", last_assistant=old)]
        self.tick()
        self.assertEqual(self.findings()[f1]["state"], "verify_sent")

    def test_ambiguous_sessions_not_read(self):
        f1 = self.fids[0]
        line = "STEWARD-REVIEW-VERDICT: %s verified\n" % f1
        self.views = [_view("a", last_assistant=line), _view("a20261022", last_assistant=line)]
        self.tick()
        self.assertEqual(self.findings()[f1]["state"], "verify_sent")


class TestDecideExport(_Flow):
    def setUp(self):
        super().setUp()
        self.fids = self.seed()

    def set_state(self, fid, st):
        d = self.findings()
        d[fid]["state"] = st
        rv.save_findings(self.p, d)

    def test_approve_rules(self):
        f1, f2, f3 = self.fids
        for st in ("new", "verify_sent", "refuted"):
            self.set_state(f1, st)
            r = self.post("finding", id=f1, action="approve")
            self.assertFalse(r["ok"], st)
            self.assertEqual(self.findings()[f1]["state"], st)
        self.set_state(f1, "verified")
        self.assertTrue(self.post("finding", id=f1, action="approve")["ok"])
        self.set_state(f2, "unclear")
        self.assertTrue(self.post("finding", id=f2, action="approve")["ok"])
        self.assertTrue(self.post("finding", id=f3, action="reject")["ok"])
        d = self.findings()
        self.assertEqual((d[f1]["state"], d[f1]["decided_by"]), ("approved", "owner"))
        self.assertEqual(d[f3]["state"], "rejected")
        self.assertFalse(self.post("finding", id=f1, action="explode")["ok"])
        self.assertFalse(self.post("finding", id="yok", action="approve")["ok"])

    def test_export_only_approved_once(self):
        f1, f2, f3 = self.fids
        todo = os.path.join(self.proj_dir, "TODO.md")
        r = self.post("export", project="a")
        self.assertFalse(r["ok"])                                   # onaylı bulgu yok: dosya yazılmaz
        self.assertFalse(os.path.exists(todo))
        self.set_state(f1, "approved")
        self.set_state(f2, "verified")                              # onaysız: ASLA yazılmaz
        with open(todo, "w") as fh:
            fh.write("# TODO\n\n- mevcut madde\n")
        r = self.post("export", project="a")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["written"], [f1])
        with open(todo) as fh:
            text = fh.read()
        self.assertIn("## Review bulguları", text)
        self.assertIn(f"(review {f1})", text)
        self.assertNotIn(f2, text)
        self.assertNotIn(f3, text)
        self.assertIn("kaynak: a/evren/m1/", text)
        self.assertIn("- mevcut madde", text)
        self.assertEqual(self.findings()[f1]["state"], "exported")
        r2 = self.post("export", project="a")                       # çift dışa aktarma yok
        self.assertFalse(r2["ok"])
        with open(todo) as fh:
            self.assertEqual(fh.read(), text)

    def test_export_tbd_and_remote_rejected(self):
        self.set_state(self.fids[0], "approved")
        self.assertFalse(self.post("export", project="a", kind="zz")["ok"])
        self.assertTrue(self.post("export", project="a", kind="tbd")["ok"])
        self.assertTrue(os.path.exists(os.path.join(self.proj_dir, "TOBEDECIDED.md")))
        self.assertFalse(self.post("export", project="far")["ok"])


class TestGates(_Flow):
    def test_brain_actor_rejected_on_all_new_posts(self):
        fid = self.seed()[0]
        self.views = [_view("a")]
        for path, body in (("verify", {"project": "a"}), ("finding", {"id": fid, "action": "reject"}),
                           ("export", {"project": "a"})):
            r = self.post(path, actor="brain", **body)
            self.assertFalse(r["ok"], path)
            self.assertIn("brain cannot", r["error"])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.findings()[fid]["state"], "new")

    def test_non_reviewer_rejected(self):
        r = ws.http_post("/api/steward/review/verify", {"project": "a"})
        self.assertFalse(r["ok"])
        self.assertIn("not a reviewer", r["error"])

    def test_reviewer_target_refusal_unchanged(self):
        r = ws._target("a", "", sid="rev")
        self.assertEqual(r["code"], "reviewer")


class TestCli(_Flow):
    def setUp(self):
        super().setUp()
        self.calls = []

        def fake_api(port, method, path, body=None):
            self.calls.append((method, path, body))
            return {"ok": True, "state": "approved", "findings": [], "written": [], "already": []}

        p = mock.patch.object(cli.mcp_queue, "_api", fake_api)
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, *argv):
        ap = argparse.ArgumentParser()
        cli.register(ap.add_subparsers())
        args = ap.parse_args(["steward", "-s", "rev", *argv])
        with contextlib.redirect_stdout(io.StringIO()):
            return args.func(args)

    def test_cli_maps(self):
        self.assertEqual(self.run_cli("review", "verify", "a"), 0)
        self.assertEqual(self.run_cli("review", "verify", "a", "--fid", "x:1", "--fid", "x:2"), 0)
        self.assertEqual(self.run_cli("review", "approve", "a:b:R-1"), 0)
        self.assertEqual(self.run_cli("review", "reject", "a:b:R-2"), 0)
        self.assertEqual(self.run_cli("review", "export", "a", "--kind", "tbd"), 0)
        self.assertEqual([(c[1], c[2]) for c in self.calls], [
            ("/api/steward/review/verify", {"project": "a", "steward": "rev"}),
            ("/api/steward/review/verify", {"project": "a", "fids": ["x:1", "x:2"], "steward": "rev"}),
            ("/api/steward/review/finding", {"id": "a:b:R-1", "action": "approve", "steward": "rev"}),
            ("/api/steward/review/finding", {"id": "a:b:R-2", "action": "reject", "steward": "rev"}),
            ("/api/steward/review/export", {"project": "a", "kind": "tbd", "steward": "rev"})])


if __name__ == "__main__":
    unittest.main()


class TestAutoApprove(_Flow):
    def states(self):
        return {v["ref"]: v["state"] for v in self.findings().values()}

    def prep(self, md=REVIEW_MD + "\n## R-4 | P3 | w.py:1 | Veritabanı parolası kodda\ngovde 4\n\n## R-5 | P3 | v.py:1 | Beşinci\ngovde 5\n"):
        self.seed(md)
        data = self.findings()
        for v in data.values():
            v["state"] = "unclear" if v["ref"] == "R-5" else "verified"
        rv.save_findings(self.p, data)

    def test_level_1_approves_only_verified_p3_without_secrets(self):
        self.prep()
        done = wr.auto_approve(NS(sid="rev", review_auto_approve=1), now=5_000.0)
        self.assertEqual(len(done), 1)
        self.assertEqual(self.states(), {"R-1": "verified", "R-2": "verified", "R-3": "approved", "R-4": "verified", "R-5": "unclear"})
        self.assertEqual([v["decided_by"] for v in self.findings().values() if v["state"] == "approved"], ["auto"])

    def test_level_2_adds_p2_but_never_p1_unclear_or_secret(self):
        self.prep()
        wr.auto_approve(NS(sid="rev", review_auto_approve=2), now=5_000.0)
        self.assertEqual(self.states(), {"R-1": "verified", "R-2": "approved", "R-3": "approved", "R-4": "verified", "R-5": "unclear"})

    def test_off_and_tick_wiring(self):
        self.prep()
        self.assertEqual(wr.auto_approve(NS(sid="rev", review_auto_approve=0)), [])
        self.assertTrue(all(s != "approved" for s in self.states().values()))
        settings.save_settings({"stewards": {"rev": {"review_auto_approve": 1}}})
        res = self.tick()
        self.assertIn("auto_approve", [a["kind"] for a in res["actions"]])
        self.assertEqual(self.states()["R-3"], "approved")


class TestAutoVerify(_Flow):
    def cfg(self, on=True):
        import dataclasses
        return dataclasses.replace(ws.steward_config("rev"), review_auto_verify=on)

    def test_sends_once_per_tick_and_marks(self):
        self.seed()
        wr.sync_pool(self.p, 5_000.0)
        self.views = [_view("a", last_assistant="eski")]
        r = ws.auto_review_verify(self.cfg(), now=5_000.0)
        self.assertEqual(r["project"], "a")
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(all(v["state"] == "verify_sent" for v in self.findings().values()))
        self.assertIsNone(ws.auto_review_verify(self.cfg(), now=5_100.0))      # cevap bekleyen proje atlanır
        self.assertEqual(len(self.sent), 1)

    def test_stale_waiting_does_not_block(self):
        self.seed()
        wr.sync_pool(self.p, 5_000.0)
        data = self.findings()
        for v in data.values():
            v.update(state="verify_sent", verify_sent_at=1_000.0)
        data["a:x:extra"] = {"project": "a", "state": "new", "ref": "R-9", "severity": "P3"}
        rv.save_findings(self.p, data)
        self.views = [_view("a", last_assistant="eski")]
        self.assertEqual(ws.auto_review_verify(self.cfg(), now=1_000.0 + ws.AUTO_VERIFY_STALE_SECONDS + 1)["project"], "a")

    def test_off_and_busy_send_nothing(self):
        self.seed()
        wr.sync_pool(self.p, 5_000.0)
        self.views = [_view("a")]
        self.assertIsNone(ws.auto_review_verify(self.cfg(False), now=5_000.0))
        self.views = [_view("a", busy=True)]
        self.assertIsNone(ws.auto_review_verify(self.cfg(), now=5_000.0))
        self.assertEqual(self.sent, [])


class TestBeforeTbd(_Flow):
    def prep(self):
        self.seed(REVIEW_MD + "\n## R-4 | P3 | w.py:1 | Veritabanı parolası kodda\ngovde gizli\n")
        data = self.findings()
        for v in data.values():
            v["state"] = {"R-1": "unclear", "R-2": "refuted", "R-3": "exported", "R-4": "refuted"}[v["ref"]]
            v["verdict"] = "gerekçe " + v["ref"]
        rv.save_findings(self.p, data)
        self.out = os.path.join(self.dir.name, "prv")
        os.makedirs(self.out)
        return NS(sid="rev", review_before_tbd_dir=self.out)

    def text(self):
        files = [f for f in os.listdir(self.out) if f.startswith("BEFORETBD-")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.out, files[0]), encoding="utf-8") as f:
            return f.read()

    def test_writes_only_unclear_and_refuted_once_and_hides_secrets(self):
        cfg = self.prep()
        done = wr.before_tbd(cfg, now=1_700_000_000.0)
        self.assertEqual(len(done), 3)
        txt = self.text()
        self.assertIn("| P1 | unclear", txt)
        self.assertIn("| P2 | refuted", txt)
        self.assertNotIn("| P3 | exported", txt)
        self.assertNotIn("govde gizli", txt)
        self.assertIn("gövde yazılmadı", txt)
        self.assertEqual(wr.before_tbd(cfg, now=1_700_000_100.0), [])     # çift yazma yok
        self.assertEqual(self.text().count("## "), txt.count("## "))

    def test_off_when_dir_empty_or_missing(self):
        cfg = self.prep()
        self.assertEqual(wr.before_tbd(NS(sid="rev", review_before_tbd_dir=""), now=1.0), [])
        self.assertEqual(wr.before_tbd(NS(sid="rev", review_before_tbd_dir="/nonexistent/x"), now=1.0), [])
        self.assertEqual(os.listdir(self.out), [])

    def test_tick_wiring(self):
        cfg = self.prep()
        settings.save_settings({"stewards": {"rev": {"review_before_tbd_dir": self.out}}})
        res = self.tick()
        self.assertIn("before_tbd", [a["kind"] for a in res["actions"]])


class StoreReportsTest(unittest.TestCase):
    """TBD#118 ilk dilim: biten koşunun maskeli raporu özel klasöre kopyalanır; io/model/hata günlüğü SAKLANMAZ; git yok."""

    def test_copies_report_and_usage_once_and_skips_private_traces(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "reviews"), os.path.join(d, "prv")
            os.makedirs(out)
            run = os.path.join(src, "oiso", "evren", "m", "low", "20261024164009")
            os.makedirs(run)
            for n, body in (("20261024164009.md", "rapor"), ("20261024164009.usage.jsonl", "{}"), ("20261024164009.io.jsonl", "sır"),
                            ("20261024164009.model.md", "taslak"), ("20261024164009.err.md", "hata")):
                with open(os.path.join(run, n), "w") as f:
                    f.write(body)
            with open(os.path.join(src, "oiso", "OZET.md"), "w") as f:      # zaman damgası klasörü dışı: dokunulmaz
                f.write("x")
            cfg = NS(sid="rev", review_store_dir=out)
            with mock.patch.object(sw, "_pp", lambda sid: NS(reviews=src)):
                got = wr.store_reports(cfg)
                self.assertEqual(sorted(os.path.basename(g) for g in got), ["20261024164009.md", "20261024164009.usage.jsonl"])
                self.assertEqual(wr.store_reports(cfg), [])                    # ikinci tur: yeniden yazılmaz
            dst = os.path.join(out, "reviews", "oiso", "evren", "m", "low", "20261024164009")
            self.assertEqual(sorted(os.listdir(dst)), ["20261024164009.md", "20261024164009.usage.jsonl"])
            self.assertFalse(os.path.exists(os.path.join(out, ".git")))
            with mock.patch.object(sw, "_pp", lambda sid: NS(reviews=src)):
                self.assertEqual(wr.store_reports(NS(sid="rev", review_store_dir="")), [])
                self.assertEqual(wr.store_reports(NS(sid="rev", review_store_dir=os.path.join(d, "yok"))), [])
                self.assertEqual(wr.store_reports(NS(sid="rev", review_store_dir=src)), [])   # hedef kaynağın içi: özyineleme yok

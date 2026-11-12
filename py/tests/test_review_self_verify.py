"""TBD#137 a=A + b: reviewer'ın KENDİ salt-okunur `claude -p` doğrulaması (proje oturumu uyanmaz) ve toplu onay.
Gerçek süreç YOK: `popen=` sahte, `NoRealReviewMixin` gerçek Popen'u yasaklar.
Çalıştırma: python3 -m unittest discover -s py/tests"""
import dataclasses
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_review_findings_flow import _Flow  # noqa: E402
from claudeops import review as rv, steward as sw  # noqa: E402
from claudeops.commands import web_review as wr, web_steward as ws  # noqa: E402


class Proc:
    def __init__(self, out="", rc=0, hang=False):
        self.out, self.returncode, self.hang, self.killed = out, rc, hang, False

    def communicate(self, timeout=None):
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired("claude", timeout)
        return self.out, ""

    def kill(self):
        self.killed = True


def _out(findings, verdicts):
    return "inceledim\n" + "\n".join(f"{rv.VERDICT_MARK} {f} {v} gerekçe" for f, v in zip(findings, verdicts))


class SelfVerifyTest(_Flow):
    def setUp(self):
        super().setUp()
        self.argvs = []
        from claudeops import settings
        settings.save_settings({"stewards": {"rev": {"enabled": "on", "mode": "act", "role": "reviewer",
                                                     "review_verify_mode": "self"}}})
        self.cfg = ws.steward_config("rev")
        self.assertEqual(self.cfg.review_verify_mode, "self")

    def popen(self, proc):
        def f(argv, **k):
            self.argvs.append((argv, k))
            return proc
        return f

    def rows(self):
        return wr.verify_candidates(self.cfg, "a")

    def test_verdicts_applied_session_not_woken(self):
        fids = self.seed()
        rows = self.rows()
        ids = [r["id"] for r in rows]
        res = wr.self_verify(self.cfg, "a", rows, popen=self.popen(Proc(_out(ids, ["verified", "refuted", "unclear"]))), background=False)
        self.assertTrue(res["ok"])
        st = [self.findings()[i]["state"] for i in ids]
        self.assertEqual(st, ["verified", "refuted", "unclear"])
        self.assertEqual(self.sent, [])                      # proje oturumuna direktif GİTMEDİ
        argv, kw = self.argvs[0]
        self.assertIn("--allowedTools", argv)
        self.assertNotIn("Edit", argv[argv.index("--allowedTools"):argv.index("--disallowedTools")])
        self.assertEqual(kw["cwd"], self.proj_dir)
        self.assertEqual(len(fids), 3)

    def test_failure_returns_to_new_then_unclear_after_max_tries(self):
        self.seed()
        for n in range(wr.SELF_VERIFY_MAX_TRIES):
            rows = self.rows()
            self.assertTrue(rows, n)
            wr.self_verify(self.cfg, "a", rows, popen=self.popen(Proc("", rc=1)), background=False)
        self.assertEqual({v["state"] for v in self.findings().values()}, {"unclear"})
        self.assertIn("denemede", next(iter(self.findings().values()))["verdict"])

    def test_apply_verdicts_exception_requeues_not_stuck(self):
        """review R-2: karar uygulaması patlarsa bulgular `verify_sent`te takılı kalmaz, `new`e döner."""
        self.seed()
        rows = self.rows()
        ids = [r["id"] for r in rows]
        with mock.patch.object(wr.rv, "apply_verdicts", side_effect=RuntimeError("boom")):
            res = wr.self_verify(self.cfg, "a", rows, popen=self.popen(Proc(_out(ids, ["verified"] * len(ids)))), background=False)
        self.assertTrue(res["ok"])
        states = {self.findings()[i]["state"] for i in ids}
        self.assertEqual(states, {"new"})
        self.assertNotIn("verify_sent", states)

    def test_timeout_kills_and_requeues(self):
        self.seed()
        proc = Proc(hang=True)
        with mock.patch.object(wr, "SELF_VERIFY_TIMEOUT", 0.01):
            wr.self_verify(self.cfg, "a", self.rows(), popen=self.popen(proc), background=False)
        self.assertTrue(proc.killed)
        self.assertEqual({v["state"] for v in self.findings().values()}, {"new"})

    def test_concurrent_calls_same_project_only_one_starts(self):
        """Denetle+yer ayır tek kilitte: iki eşzamanlı çağrıdan yalnız biri başlar, diğeri already_running."""
        import threading
        self.seed()
        rows = self.rows()
        gate, entered = threading.Event(), threading.Event()
        started = []

        class Slow(Proc):
            def communicate(inner, timeout=None):
                entered.set()
                gate.wait(5)
                return "", ""

        def popen(argv, **k):
            started.append(1)
            return Slow()
        results = []
        ts = [threading.Thread(target=lambda: results.append(wr.self_verify(self.cfg, "a", rows, popen=popen, background=False)))
              for _ in range(2)]
        for t in ts:
            t.start()
        self.assertTrue(entered.wait(5))
        for _ in range(100):
            if any(not r["ok"] for r in results):
                break
            threading.Event().wait(0.02)
        self.assertEqual([r.get("code") for r in results if not r["ok"]], ["already_running"])
        gate.set()
        for t in ts:
            t.join(10)
        self.assertEqual(len(started), 1)

    def test_missing_verdict_line_requeues_only_that_finding(self):
        self.seed()
        ids = [r["id"] for r in self.rows()]
        wr.self_verify(self.cfg, "a", self.rows(), popen=self.popen(Proc(_out(ids[:2], ["verified", "verified"]))), background=False)
        st = {i: self.findings()[i]["state"] for i in ids}
        self.assertEqual([st[i] for i in ids], ["verified", "verified", "new"])

    def test_recover_returns_orphaned_self_verify_to_new(self):
        self.seed()
        rows = self.rows()
        rv.mark_verify_sent(self.p, [r["id"] for r in rows], "self", "", 1.0)
        self.assertEqual(wr.recover_self_verify(self.p), 3)
        self.assertEqual({v["state"] for v in self.findings().values()}, {"new"})

    def test_process_verdicts_ignores_self_sessions(self):
        self.seed()
        rows = self.rows()
        rv.mark_verify_sent(self.p, [r["id"] for r in rows], "self", "", 1.0)
        seen = []
        with mock.patch.object(wr, "_VERDICT_READER", lambda proj: seen.append(proj) or ("s", "x")):
            wr.process_verdicts(self.cfg, 5_000.0)
        self.assertEqual(seen, [])

    def test_http_verify_and_auto_verify_use_self_mode(self):
        self.seed()
        wr.sync_pool(self.p, 5_000.0)
        calls = []
        with mock.patch.object(wr, "self_verify", lambda cfg, proj, rows, **k: calls.append((proj, len(rows))) or {"ok": True, "findings": []}):
            ws.auto_review_verify(dataclasses.replace(self.cfg, review_auto_verify=True), now=5_000.0)
        self.assertEqual(calls, [("a", 3)])
        self.assertEqual(self.sent, [])

    def test_bulk_approve_only_verified_filtered(self):
        self.seed()
        ids = [r["id"] for r in self.rows()]
        data = self.findings()
        for i, s in zip(ids, ("verified", "verified", "refuted")):
            data[i]["state"] = s
        rv.save_findings(self.p, data)
        r = wr.bulk_decide(self.cfg, "approve", project="a", severities=["P2"])
        self.assertEqual(len(r["done"]), 1)
        self.assertEqual(self.findings()[r["done"][0]]["severity"], "P2")
        r = wr.bulk_decide(self.cfg, "approve")
        self.assertEqual(len(r["done"]), 1)                    # kalan verified; refuted dokunulmaz
        self.assertEqual(self.findings()[ids[2]]["state"], "refuted")
        self.assertFalse(wr.bulk_decide(self.cfg, "nuke")["ok"])

    def test_bulk_endpoint_is_human_only(self):
        self.seed()
        r = ws.http_post("/api/steward/review/bulk", {"steward": "rev", "action": "approve", "actor": "brain"})
        self.assertFalse(r.get("ok"))

    # ── doğrulayıcı sağlayıcısı (review_verify_provider/model, 2026-11-09) ──
    def test_default_verifier_is_claude_sonnet(self):
        self.assertEqual((wr.verify_provider(self.cfg), wr.verify_model(self.cfg)), ("claude", wr.SELF_VERIFY_MODEL))

    def test_codex_verifier_read_only_argv(self):
        self.seed()
        cfg = dataclasses.replace(self.cfg, review_verify_provider="codex", review_codex_models="gpt-5.5@low,x")
        rows = wr.verify_candidates(cfg, "a")
        ids = [r["id"] for r in rows]
        res = wr.self_verify(cfg, "a", rows, popen=self.popen(Proc(_out(ids, ["verified"] * 3))), background=False)
        self.assertTrue(res["ok"])
        argv, _kw = self.argvs[0]
        self.assertIn("exec", argv)
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5.5")
        self.assertEqual({self.findings()[i]["state"] for i in ids}, {"verified"})

    def test_evren_verifier_waits_for_running_evren_review_and_has_no_allow_flags(self):
        self.seed()
        cfg = dataclasses.replace(self.cfg, review_verify_provider="evren", review_verify_model="glm-5.3")
        rows = wr.verify_candidates(cfg, "a")
        with mock.patch.object(wr, "running_keys", lambda sid="": ["b|evren/qwen"]):
            res = wr.self_verify(cfg, "a", rows, popen=self.popen(Proc("")), background=False)
        self.assertEqual(res.get("code"), "verifier_busy")
        self.assertEqual(self.argvs, [])
        self.assertEqual({self.findings()[r["id"]]["state"] for r in rows}, {"new"})     # işaretlenmedi
        with mock.patch.object(wr, "_api_key", lambda: "k"), mock.patch.object(wr, "running_keys", lambda sid="": []), \
                mock.patch("claudeops.providers.ucli_provider.endpoint", lambda: "https://e/v1"):
            ids = [r["id"] for r in rows]
            res = wr.self_verify(cfg, "a", rows, popen=self.popen(Proc(_out(ids, ["refuted"] * 3))), background=False)
        self.assertTrue(res["ok"])
        argv, kw = self.argvs[0]
        self.assertFalse([a for a in argv if a.startswith("--allow-")])
        self.assertEqual(argv[argv.index("--model") + 1], "glm-5.3")
        self.assertEqual(kw["env"].get("UCLI_API_KEY"), "k")

    def test_missing_model_is_busy_not_marked(self):
        self.seed()
        cfg = dataclasses.replace(self.cfg, review_verify_provider="agy", review_agy_models="")
        res = wr.self_verify(cfg, "a", wr.verify_candidates(cfg, "a"), popen=self.popen(Proc("")), background=False)
        self.assertEqual(res.get("code"), "verifier_busy")

    def test_config_accepts_provider_and_single_model(self):
        self.assertTrue(ws.http_config({"key": "review_verify_provider", "value": "evren"}, sid="rev")["ok"])
        self.assertFalse(ws.http_config({"key": "review_verify_provider", "value": "copilot"}, sid="rev")["ok"])
        self.assertTrue(ws.http_config({"key": "review_verify_model", "value": "glm-5.3"}, sid="rev")["ok"])
        self.assertFalse(ws.http_config({"key": "review_verify_model", "value": "a,b"}, sid="rev")["ok"])
        self.assertEqual(wr.verify_model(ws.steward_config("rev")), "glm-5.3")

if __name__ == "__main__":
    unittest.main()

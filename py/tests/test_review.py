"""review.py saf çekirdek testleri: ağ/süreç yok; yollar geçici dizine yönlendirilir."""
import dataclasses
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402
from claudeops import settings  # noqa: E402
from claudeops import steward as sw  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400.0
T1 = rv.ReviewTarget("agy", "gemini-3-flash", "gemini-3-flash")
T2 = rv.ReviewTarget("evren", "glm/4.6", "glm-4.6")
TS = [T1, T2]


def done(at, status="done"):
    return {"status": status, "started_at": at - 60, "finished_at": at, "attempts": 1}


def pool(*names):
    return {"projects": {n: {"enabled": True, "source": "auto", "added_at": 1, "removed_at": None} for n in names}}


def hist(**pairs):
    return {"version": 1, "pairs": pairs, "runs": []}


class TestSlugTargets(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(rv.slug_model("glm/4.6"), "glm-4.6")
        self.assertEqual(rv.slug_model("../../etc/passwd"), "etc-passwd")
        self.assertEqual(rv.slug_model("a b//c"), "a-b-c")
        self.assertEqual(rv.slug_model(""), "model")
        self.assertEqual(rv.slug_model(".."), "model")

    def test_targets_all_and_filtered(self):
        cfg = sw.Config()
        t = rv.targets_from_config(cfg, ["a", "b"], ["x/y"])
        self.assertEqual([(x.mode, x.model, x.slug) for x in t], [("agy", "a", "a"), ("agy", "b", "b"), ("evren", "x/y", "x-y")])
        cfg.review_agy_models = "b, nope"
        cfg.review_evren_models = "x/y,x/y"
        t = rv.targets_from_config(cfg, ["a", "b"], ["x/y"])
        self.assertEqual([x.key for x in t], ["agy/b", "evren/x-y"])

    def test_claude_mode_opt_in(self):
        cfg = sw.Config()
        self.assertEqual([x.mode for x in rv.targets_from_config(cfg, [], [])], [])    # varsayılan KAPALI
        cfg.review_claude_models = "claude-haiku-5-5, claude-haiku-5-5"
        t = rv.targets_from_config(cfg, [], [])
        self.assertEqual([(x.mode, x.model, x.key) for x in t], [("claude", "claude-haiku-5-5", "claude/claude-haiku-5-5")])
        cfg.review_codex_models = "gpt-6-luna"
        self.assertEqual([x.key for x in rv.targets_from_config(cfg, [], [])], ["claude/claude-haiku-5-5", "codex/gpt-6-luna"])


class TestPlanner(unittest.TestCase):
    def test_complete_window(self):
        h = hist(**{"p|agy/gemini-3-flash": done(NOW - DAY), "p|evren/glm-4.6": done(NOW - 2 * DAY)})
        self.assertTrue(rv.project_complete(h, "p", TS, NOW))
        h["pairs"]["p|evren/glm-4.6"] = done(NOW - 31 * DAY)
        self.assertFalse(rv.project_complete(h, "p", TS, NOW))
        h["pairs"]["p|evren/glm-4.6"] = done(NOW - DAY, "partial")
        self.assertFalse(rv.project_complete(h, "p", TS, NOW))
        self.assertFalse(rv.project_complete(h, "p", [], NOW))

    def test_order_partial_then_never_then_oldest(self):
        h = hist(**{
            "half|agy/gemini-3-flash": done(NOW - DAY),                       # yarım: evren eksik
            "old|agy/gemini-3-flash": done(NOW - 40 * DAY), "old|evren/glm-4.6": done(NOW - 40 * DAY),
            "older|agy/gemini-3-flash": done(NOW - 90 * DAY), "older|evren/glm-4.6": done(NOW - 90 * DAY),
        })
        p = pool("half", "never", "old", "older", "full")
        h["pairs"]["full|agy/gemini-3-flash"] = done(NOW - DAY)
        h["pairs"]["full|evren/glm-4.6"] = done(NOW - DAY)
        self.assertEqual(rv.next_review(p, h, TS, NOW), ("half", T2))
        h["pairs"]["half|evren/glm-4.6"] = done(NOW - DAY)
        self.assertEqual(rv.next_review(p, h, TS, NOW), ("never", T1))
        h["pairs"]["never|agy/gemini-3-flash"] = done(NOW - DAY)
        h["pairs"]["never|evren/glm-4.6"] = done(NOW - DAY)
        self.assertEqual(rv.next_review(p, h, TS, NOW), ("older", T1))

    def test_busy_running_disabled_and_empty(self):
        p = pool("a", "b")
        self.assertEqual(rv.next_review(p, hist(), TS, NOW, busy_projects=["a"])[0], "b")
        h = hist(**{"a|agy/gemini-3-flash": {"status": "running", "started_at": NOW}})
        self.assertEqual(rv.next_review(p, h, TS, NOW)[0], "b")
        p["projects"]["b"]["enabled"] = False
        self.assertIsNone(rv.next_review(p, h, TS, NOW))
        self.assertIsNone(rv.next_review(pool("a"), hist(), [], NOW))
        p2 = pool("a")
        p2["projects"]["a"]["removed_at"] = 5
        self.assertIsNone(rv.next_review(p2, hist(), TS, NOW))

    def test_attempt_cap(self):
        bad = {"status": "error", "started_at": NOW - DAY, "attempts": 3}
        h = hist(**{"a|agy/gemini-3-flash": bad})
        self.assertEqual(rv.next_review(pool("a"), h, TS, NOW), ("a", T2))
        bad["attempts"] = 1
        self.assertEqual(rv.next_review(pool("a"), h, TS, NOW), ("a", T1))


class TestPoolSync(unittest.TestCase):
    def test_sync(self):
        p0 = {"projects": {"man": {"enabled": True, "source": "manual", "added_at": 1, "removed_at": None},
                           "gone": {"enabled": True, "source": "auto", "added_at": 1, "removed_at": None}}}
        p1, ch = rv.pool_sync(p0, ["new", "man"], NOW)
        self.assertTrue(ch)
        self.assertEqual(p1["projects"]["new"]["source"], "auto")
        self.assertFalse(p1["projects"]["gone"]["enabled"])
        self.assertEqual(p1["projects"]["gone"]["removed_at"], NOW)
        self.assertTrue(p1["projects"]["man"]["enabled"])
        self.assertTrue(p0["projects"]["gone"]["enabled"])             # girdi değişmedi
        p2, ch2 = rv.pool_sync(p1, ["new", "man", "gone"], NOW + 1)     # geri geldi
        self.assertTrue(ch2 and p2["projects"]["gone"]["enabled"] and p2["projects"]["gone"]["removed_at"] is None)
        _, ch3 = rv.pool_sync(p2, ["new", "man", "gone"], NOW + 2)
        self.assertFalse(ch3)
        # elle kapatılmış auto kayıt (removed_at yok, enabled False) yeniden AÇILMAZ
        p2["projects"]["new"]["enabled"] = False
        p4, _ = rv.pool_sync(p2, ["new"], NOW + 3)
        self.assertFalse(p4["projects"]["new"]["enabled"])


MD = """intro
## R-1 | P1 | py/a.py:10 | Kilit eksik
Gövde bir.
```
## R-9 | P1 | x:1 | çit içi
```
satır
### R-2 | P3 | README.md | Eski belge
Gövde iki.
## R-1 | P2 | tekrar | yinelenen
# Sonuç
bitti
"""


class TestParse(unittest.TestCase):
    def test_findings(self):
        f = rv.parse_findings(MD)
        self.assertEqual([x["ref"] for x in f], ["R-1", "R-2"])
        self.assertEqual((f[0]["severity"], f[0]["where"], f[0]["title"]), ("P1", "py/a.py:10", "Kilit eksik"))
        self.assertIn("çit içi", f[0]["body"])
        self.assertTrue(f[0]["body"].startswith("Gövde bir."))
        self.assertEqual(f[1]["body"], "Gövde iki.")
        self.assertEqual(rv.parse_findings("BULGU YOK"), [])
        self.assertEqual(rv.parse_findings(""), [])

    def test_prompt(self):
        for lang in ("tr", "en"):
            p = rv.build_review_prompt("proj", "/w", lang)
            self.assertIn("CLAUDE.md", p)
            self.assertIn("R-1 | P2", p)
            self.assertIn("/w", p)
        self.assertEqual(len(rv.parse_findings("## R-1 | P2 | f:1 | t\ngövde")), 1)


class TestRedactLabel(unittest.TestCase):
    def test_redact(self):
        s = ("key sk-abcdefghijklmnop1234 and ghp_" + "a" * 24 + " Bearer abcdefghijklmnopqrstu\n"
             "token = hunter2hunter2\n-----BEGIN RSA PRIVATE KEY-----\nxx\n-----END RSA PRIVATE KEY-----\nnormal text")
        r = rv.redact_secrets(s)
        for leak in ("sk-abcdef", "ghp_aaaa", "abcdefghijklmnopqrstu", "hunter2", "xx\n-----END"):
            self.assertNotIn(leak, r)
        self.assertIn("normal text", r)
        self.assertIn("token = [REDACTED]", r)

    def test_agy_label(self):
        log = ("a\nPropagating selected model override model=x label=Gemini 3 Flash\n"
               "I Propagating selected model override id=1 label=gemini-3-flash\n")
        self.assertEqual(rv.agy_label_ok(log, "gemini-3-flash"), (True, "gemini-3-flash"))
        self.assertEqual(rv.agy_label_ok(log, "claude-opus"), (False, "gemini-3-flash"))
        self.assertEqual(rv.agy_label_ok("hiç yok", "m"), (False, ""))
        self.assertEqual(rv.agy_label_ok('Propagating selected model override label="Claude Sonnet 4"', "claude-sonnet-4")[0], True)


class TestPathsAndStores(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = mock.patch.object(sw, "STEWARD_DIR", self.d)
        p.start()
        self.addCleanup(p.stop)
        self.paths = sw.paths_for("reviewer")

    def test_paths(self):
        p = self.paths
        r = os.path.join(self.d, "stewards", "reviewer")
        self.assertEqual((p.reviews, p.review_pool, p.review_history, p.findings),
                         (os.path.join(r, "reviews"), os.path.join(r, "review_pool.json"),
                          os.path.join(r, "review_history.json"), os.path.join(r, "findings.json")))
        self.assertTrue(sw.valid_custom_id("reviewer"))

    def test_review_path(self):
        out = rv.review_path(self.paths.reviews, "my/proj", T2, 0)
        self.assertRegex(out, r"reviews/my-proj/evren/glm-4\.6/\d{14}\.md$")
        self.assertTrue(rv.review_path("/r", "p", T1, "20261022101500").endswith("/p/agy/gemini-3-flash/20261022101500.md"))

    def test_history_and_pool_roundtrip(self):
        self.assertEqual(rv.load_pool(self.paths), {"projects": {}})
        rv.save_pool(self.paths, pool("a"))
        self.assertEqual(rv.pool_enabled(rv.load_pool(self.paths)), ["a"])
        r = rv.update_pair(self.paths, "a", T1, status="running", started_at=NOW)
        self.assertEqual(r["attempts"], 1)
        r = rv.update_pair(self.paths, "a", T1, status="running", started_at=NOW)
        self.assertEqual(r["attempts"], 2)
        rv.update_pair(self.paths, "a", T1, status="done", finished_at=NOW, file="f.md")
        h = rv.load_history(self.paths)
        self.assertEqual(h["pairs"]["a|agy/gemini-3-flash"]["status"], "done")
        self.assertEqual(len(h["runs"]), 1)
        with self.assertRaises(ValueError):
            rv.update_pair(self.paths, "a", T1, status="bogus")
        for i in range(250):
            rv.update_pair(self.paths, "a", T1, status="error", finished_at=NOW + i)
        self.assertEqual(len(rv.load_history(self.paths)["runs"]), rv.HISTORY_RUNS_MAX)

    def test_findings_store(self):
        f = rv.parse_findings(MD)
        rf = os.path.join(self.paths.reviews, "a", "agy", "m", "20261022101500.md")
        ids = rv.add_findings(self.paths, "a", rf, f)
        self.assertEqual(len(ids), 2)
        self.assertEqual(rv.add_findings(self.paths, "a", rf, f), [])
        data = rv.load_findings(self.paths)
        self.assertEqual(data[ids[0]]["state"], "new")
        self.assertIn(data[ids[0]]["state"], rv.FINDING_STATES)


class TestConfigRole(unittest.TestCase):
    def test_defaults_and_settings(self):
        c = sw.Config()
        self.assertEqual((c.role, c.review_timeout_minutes), ("steward", 45))
        d = tempfile.mkdtemp()
        sj = os.path.join(d, "settings.json")
        with mock.patch.object(settings, "SETTINGS_JSON", sj):
            import json
            with open(sj, "w") as f:
                json.dump({"stewards": {"reviewer": {"role": "reviewer", "review_agy_models": "a,b",
                                                     "review_timeout_minutes": "30"},
                                        "bozuk": {"role": "xx"}}}, f)
            cfg = settings.steward_config("reviewer")
            self.assertEqual((cfg.role, cfg.review_agy_models, cfg.review_timeout_minutes), ("reviewer", "a,b", 30))
            self.assertEqual(settings.steward_config("bozuk").role, "steward")
            self.assertEqual(settings.steward_config().role, "steward")


if __name__ == "__main__":
    unittest.main()


class TestClaudeArgv(unittest.TestCase):
    def test_claude_argv_read_only_and_prompt_first(self):
        from claudeops.commands import web_review as wr
        a = wr.claude_argv("/bin/claude", "claude-haiku-5-5", "low", "PROMPT")
        self.assertEqual(a[:4], ["/bin/claude", "-p", "PROMPT", "--model"])
        self.assertIn("--effort", a)
        self.assertLess(a.index("PROMPT"), a.index("--allowedTools"))     # değişken sayılı bayrak promptu yutmasın
        for forbidden in ("Edit", "Write", "NotebookEdit"):
            self.assertIn(forbidden, a[a.index("--disallowedTools"):])
            self.assertNotIn(forbidden, a[a.index("--allowedTools"):a.index("--disallowedTools")])
        self.assertNotIn("--dangerously-skip-permissions", a)
        self.assertEqual(wr.claude_argv("b", "m", "", "P").count("--effort"), 0)


class TestCodexArgv(unittest.TestCase):
    def test_codex_argv_read_only(self):
        from claudeops.commands import web_review as wr
        a = wr.codex_argv("/bin/codex", "/w", "gpt-6-luna", "low", "PROMPT")
        self.assertEqual(a[:5], ["/bin/codex", "exec", "-s", "read-only", "--skip-git-repo-check"])
        self.assertEqual(a[-1], "PROMPT")
        self.assertIn("model_reasoning_effort=low", a)
        self.assertNotIn("workspace-write", a)
        self.assertNotIn("danger-full-access", a)
        self.assertEqual(wr.codex_argv("b", "/w", "m", "", "P").count("-c"), 0)

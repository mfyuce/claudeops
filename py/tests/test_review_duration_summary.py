"""Reviewer koşu süresi: runs kaydına `seconds`, tüm sağlayıcılar için `duration_summary` (stdlib unittest)."""
import tempfile
import unittest
from unittest import mock

from claudeops import review as rv
from claudeops import steward as sw


class DurationTest(unittest.TestCase):
    def test_run_seconds(self):
        self.assertEqual(rv._run_seconds({"started_at": 100.0, "finished_at": 142.04}), 42.0)
        self.assertIsNone(rv._run_seconds({"finished_at": 5.0}))
        self.assertIsNone(rv._run_seconds({"started_at": 10.0, "finished_at": 5.0}))
        self.assertIsNone(rv._run_seconds({"started_at": "x", "finished_at": 5.0}))

    def test_update_pair_records_seconds_in_runs(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sw, "STEWARD_DIR", d):
            p = sw.paths_for("reviewer")
            t = rv.ReviewTarget("claude", "m1", "m1")
            rv.update_pair(p, "proj", t, status="running", started_at=100.0)
            rv.update_pair(p, "proj", t, status="done", finished_at=130.0, file="/x.md")
            runs = rv.load_history(p)["runs"]
            self.assertEqual(runs[-1]["seconds"], 30.0)

    def test_duration_summary(self):
        h = {"runs": [
            {"pair": "a|claude/m", "seconds": 30.0}, {"pair": "a|claude/m", "seconds": 12.5},
            {"pair": "a|claude/m"},                                    # eski kayıt: süre yok -> bilinmiyor
            {"pair": "b|codex/x", "seconds": 100}, {"pair": "bozuk"}, {"pair": "a|agy/y", "seconds": True}]}
        rows = rv.duration_summary(h)
        self.assertEqual([(r["project"], r["target"], r["runs"], r["seconds"], r["unknown"]) for r in rows],
                         [("b", "codex/x", 1, 100.0, 0), ("a", "claude/m", 3, 42.5, 1), ("a", "agy/y", 1, 0.0, 1)])
        self.assertEqual(len(rv.duration_summary(h, "a")), 2)
        self.assertEqual(rv.duration_summary(None), [])


class StaleTextTest(unittest.TestCase):
    def test_where_relpath(self):
        self.assertEqual(rv.where_relpath({"where": "src/a.py:10"}), "src/a.py")
        self.assertEqual(rv.where_relpath({"where": "../etc/x.py:1"}), "")
        self.assertEqual(rv.where_relpath({"where": "/etc/x.py:1"}), "")
        self.assertEqual(rv.where_relpath({"where": "yok"}), "")

    def test_stale_reason_text(self):
        row = {"title": "`foo_bar` bozuk"}
        self.assertIsNone(rv.stale_reason_text(row, None))                   # okunamadı
        self.assertIsNone(rv.stale_reason_text(row, "def foo_bar(): pass"))
        self.assertIn("foo_bar", rv.stale_reason_text(row, "def other(): pass"))
        self.assertIsNone(rv.stale_reason_text({"title": "ad yok"}, "x"))


class ClaudeJsonTest(unittest.TestCase):
    RES = ('{"type":"result","is_error":false,"duration_ms":42500,"result":"## R-1 | P2 | a.py:1 | x","total_cost_usd":0.017,'
           '"usage":{"input_tokens":10,"cache_read_input_tokens":200,"cache_creation_input_tokens":30,"output_tokens":55}}')

    def test_argv_json_flag_only_for_review(self):
        from claudeops.commands import web_review as wr
        a = wr.claude_argv("b", "m", "low", "P", json_out=True)
        self.assertEqual(a[a.index("--output-format") + 1], "json")
        self.assertLess(a.index("--output-format"), a.index("--allowedTools"))
        self.assertNotIn("--output-format", wr.claude_argv("b", "m", "low", "P"))      # öz-doğrulama düz metin okur

    def test_extract_and_usage(self):
        from claudeops.commands import web_review as wr
        self.assertEqual(wr._extract_text("claude", self.RES), ("## R-1 | P2 | a.py:1 | x", ""))
        ev = wr.claude_usage_event(self.RES)
        self.assertEqual(ev["usage"], {"prompt_tokens": 240, "completion_tokens": 55, "cached_tokens": 200})
        self.assertEqual((ev["seconds"], ev["cost_usd"]), (42.5, 0.017))
        arr = "[" + '{"type":"system"},' + self.RES + "]"                       # dizi biçimi: SON result
        self.assertEqual(wr._extract_text("claude", arr)[0], "## R-1 | P2 | a.py:1 | x")

    def test_non_json_and_errors_fall_back(self):
        from claudeops.commands import web_review as wr
        self.assertEqual(wr._extract_text("claude", "düz metin rapor"), ("düz metin rapor", ""))
        self.assertIsNone(wr.claude_usage_event("düz metin rapor"))
        self.assertIsNone(wr.claude_usage_event('{"type":"result","result":"x"}'))   # usage yok: uydurma yok
        t, e = wr._extract_text("claude", '{"type":"result","is_error":true,"result":"API Error 529"}')
        self.assertEqual((t, e), ("API Error 529", "API Error 529"))
        self.assertEqual(wr._extract_text("codex", self.RES), (self.RES, ""))        # diğer modlar değişmez


class CodexUsageTest(unittest.TestCase):
    def test_parse(self):
        from claudeops.commands import web_review as wr
        ev = wr.codex_usage_event("x\ntokens used\n15,008\n")                  # gerçek codex stderr biçimi
        self.assertEqual(ev["usage"], {"total_tokens": 15008})
        self.assertEqual(wr.codex_usage_event("tokens used: 1.234")["usage"]["total_tokens"], 1234)
        self.assertEqual(wr.codex_usage_event("tokens used\n10\ntokens used\n20")["usage"]["total_tokens"], 20)
        self.assertIsNone(wr.codex_usage_event("sayı yok"))
        self.assertIsNone(wr.codex_usage_event(""))
        self.assertIsNone(wr.codex_usage_event(None))

    def test_summary_totals_without_invented_split(self):
        import json, os
        with tempfile.TemporaryDirectory() as d:
            dd = os.path.join(d, "proj", "codex", "m", "medium", "20260101000000")
            os.makedirs(dd)
            with open(os.path.join(dd, "20260101000000.usage.jsonl"), "w") as f:
                f.write(json.dumps({"event": "request", "usage": {"total_tokens": 15008}}) + "\n")
            (row,) = rv.usage_summary(d)
            self.assertEqual((row["total_tokens"], row["prompt_tokens"], row["completion_tokens"]), (15008, 0, 0))


if __name__ == "__main__":
    unittest.main()


class RunDurTest(unittest.TestCase):
    def test_run_dur(self):
        from claudeops.commands.steward import _run_dur
        self.assertEqual(_run_dur(42.0), "42sn")
        self.assertEqual(_run_dur(0.4), "0sn")
        self.assertEqual(_run_dur(59.6), "1dk")
        self.assertEqual(_run_dur(180), "3dk")
        for bad in (None, True, "x", -1):
            self.assertEqual(_run_dur(bad), "-")

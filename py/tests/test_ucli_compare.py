"""ucli oturumları arası maliyet + kaynak karşılaştırma tablosu (TODO 30 (d)): `ucli_usage` (Claude, USD) + `ucli_usage/other`
(Claude DIŞI: USD YOK, bilinmeyen model opus fiyatıyla sayılmaz) + `ucli_metrics.db` (RSS/CPU/IO). Saf dosya okuma, ağ/süreç yok."""
import json
import os
import tempfile
import unittest

from claudeops import ucli_compare as uc
from claudeops import ucli_metrics as um


def write_log(path, model, reqs, t0=1_000_000, step=60_000, usage=None):
    """reqs istek, her biri `step` ms arayla; her istek: prompt 1000 (önbellek yazma 200 + okuma 300), çıktı 100."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    u = usage or {"prompt_tokens": 1000, "completion_tokens": 100, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 200}
    with open(path, "w") as f:
        f.write(json.dumps({"event": "open", "t": t0}) + "\n")
        f.write(json.dumps({"event": "task_start", "model": model, "t": t0, "task": 1}) + "\n")
        for i in range(reqs):
            f.write(json.dumps({"event": "request", "t": t0 + i * step, "seconds": 2.0, "task": 1, "usage": u}) + "\n")
        f.write(json.dumps({"event": "task_end", "t": t0 + reqs * step, "task": 1}) + "\n")


class SlowSampling(unittest.TestCase):
    def test_claude_cli_sessions_sampled_at_most_once_a_minute(self):
        t = [1000.0]
        db = os.path.join(tempfile.mkdtemp(), "m.db")
        s = um.Sampler(discover=lambda: [("x", os.getpid(), "")], path=db, now=lambda: t[0], disk=lambda c: None)
        um.SLOW_NAMES.add("x")
        try:
            n = []
            for _ in range(6):
                n.append(s.sample_once())
                t[0] += 15
        finally:
            um.SLOW_NAMES.discard("x")
        self.assertEqual(n, [1, 0, 0, 0, 1, 0])


class Compare(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.usage = os.path.join(self.d, "ucli_usage")
        self.other = os.path.join(self.usage, "other")
        self.db = os.path.join(self.d, "m.db")
        write_log(os.path.join(self.usage, "cli1.jsonl"), "claude-sonnet-5-5", 61)            # 60 dk aralık
        write_log(os.path.join(self.other, "ev1.jsonl"), "glm-5.3", 10)
        um.write_samples([("cli1", 1.0, 100_000, 10.0, 0, 0, 3, None), ("cli1", 2.0, 300_000, 30.0, 500, 900, 3, None)], self.db)

    def rows(self):
        r = uc.compare(self.usage, self.other, self.db)
        return {x["session"]: x for x in r["rows"]}, r

    def test_claude_row_has_tokens_usd_and_rate(self):
        rows, _ = self.rows()
        x = rows["cli1"]
        self.assertEqual((x["source"], x["model"], x["requests"]), ("claude", "claude-sonnet-5-5", 61))
        self.assertEqual((x["tokens"]["out"], x["tokens"]["cache_read"], x["tokens"]["cache_write"]), (6100, 18300, 12200))
        self.assertGreater(x["usd"], 0)
        self.assertAlmostEqual(x["span_s"], 3600.0, places=1)
        self.assertAlmostEqual(x["usd_per_hour"], x["usd"], places=6)          # tam 1 saat
        self.assertAlmostEqual(x["usd_per_request"], x["usd"] / 61, places=9)
        self.assertAlmostEqual(x["wait_s"], 122.0, places=3)

    def test_non_claude_has_tokens_but_no_usd(self):
        rows, _ = self.rows()
        x = rows["ev1"]
        self.assertEqual((x["source"], x["requests"]), ("other", 10))
        self.assertIsNone(x["usd"])
        self.assertIsNone(x["usd_per_hour"])
        self.assertEqual(x["tokens"]["out"], 1000)

    def test_resources_joined_by_session_name_and_missing_is_none(self):
        rows, _ = self.rows()
        self.assertEqual(rows["cli1"]["res"]["rss_max_kib"], 300_000)
        self.assertEqual(rows["cli1"]["res"]["cpu_avg"], 20.0)
        self.assertEqual(rows["cli1"]["res"]["io_w"], 900)
        self.assertIsNone(rows["ev1"]["res"])

    def test_sampled_session_without_token_log_is_resource_only_cli_row(self):
        um.write_samples([("claude-a", 5.0, 200_000, 12.0, 10, 20, 4, None)], self.db)          # claude CLI: token günlüğü YOK
        rows, r = self.rows()
        x = rows["claude-a"]
        self.assertEqual((x["source"], x["requests"], x["usd"]), ("cli", 0, None))
        self.assertEqual(x["res"]["rss_max_kib"], 200_000)
        self.assertEqual(sum(1 for q in r["rows"] if q["session"] == "cli1"), 1)             # ucli satırı ikilenmez
        self.assertNotIn("claude-a", {q["session"] for q in uc.compare(self.usage, self.other, self.db, since=10.0)["rows"]})

    def test_by_model_aggregates(self):
        _, r = self.rows()
        m = {x["model"]: x for x in r["by_model"]}
        self.assertEqual(m["claude-sonnet-5-5"]["sessions"], 1)
        self.assertEqual(m["claude-sonnet-5-5"]["requests"], 61)
        self.assertEqual(m["claude-sonnet-5-5"]["rss_max_kib_avg"], 300_000)
        self.assertIsNone(m["glm-5.3"]["usd"])
        self.assertEqual(m["glm-5.3"]["rss_max_kib_avg"], None)

    def test_short_span_has_no_hourly_rate(self):
        write_log(os.path.join(self.usage, "short.jsonl"), "claude-sonnet-5-5", 2, step=10_000)
        rows, _ = self.rows()
        self.assertIsNone(rows["short"]["usd_per_hour"])
        self.assertGreater(rows["short"]["usd"], 0)

    def test_missing_dirs_and_bad_lines_do_not_raise(self):
        r = uc.compare("/yok/a", "/yok/b", "/yok/c.db")
        self.assertEqual((r["rows"], r["by_model"]), ([], []))
        p = os.path.join(self.usage, "bad.jsonl")
        open(p, "w").write("bozuk\n{\"event\":\"request\",\"t\":\"x\",\"usage\":5}\n")
        rows, _ = self.rows()
        self.assertEqual(rows["bad"]["requests"], 1)

    def test_since_filters_old_files(self):
        old = os.path.join(self.usage, "cli1.jsonl")
        os.utime(old, (1000, 1000))
        r = uc.compare(self.usage, self.other, self.db, since=2000.0)
        self.assertNotIn("cli1", {x["session"] for x in r["rows"]})

    def test_api_get(self):
        r = uc.api_get("/api/ucli/compare", {"since": ["0"]}, self.usage, self.other, self.db)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["rows"]), 2)
        self.assertFalse(uc.api_get("/api/ucli/compare", {"since": ["x"]}, self.usage, self.other, self.db)["ok"])


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from claudeops import day_usage
from claudeops.commands import usage as usage_cmd


def _row(mid, rid, ts, i=1, o=1, cw=0, cr=0, uuid=None):
    return json.dumps({"type": "assistant", "uuid": uuid or mid + rid, "requestId": rid, "timestamp": ts,
                       "message": {"id": mid, "model": "claude-sonnet-5", "usage": {
                           "input_tokens": i, "output_tokens": o, "cache_creation_input_tokens": cw,
                           "cache_read_input_tokens": cr}}}) + "\n"


def _write(path, *rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("".join(rows))


class DayUsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        self.ts = noon.astimezone(timezone.utc).isoformat()
        self.old = (noon - timedelta(days=3)).astimezone(timezone.utc).isoformat()
        self.day = noon.strftime("%Y-%m-%d")

    def tearDown(self):
        self.tmp.cleanup()

    def test_categories_dedup_and_day(self):
        r = self.root
        _write(f"{r}/-home-x-proj/s1.jsonl", _row("m1", "r1", self.ts, 10, 2, 100, 1000),
               _row("m1", "r1", self.ts, 10, 4, 100, 1000), _row("m0", "r0", self.old, 999, 999), "bozuk satir \"usage\"\n")
        _write(f"{r}/-home-x-proj/s1/subagents/agent-a.jsonl", _row("m2", "r2", self.ts, 1, 1))
        _write(f"{r}/-home-x-degnekci_ucli/b1.jsonl", _row("m3", "r3", self.ts, 5, 5))
        _write(f"{r}/-home-x-degnekci/b2.jsonl", _row("m4", "r4", self.ts, 5, 5))
        _write(f"{r}/-home-u--claude-claudeops-steward-stewards-ucli-workspace/b3.jsonl", _row("m5", "r5", self.ts))
        d = day_usage.collect_day(self.day, r)
        c = d["categories"]
        self.assertEqual(c["project"]["turns"], 1)
        self.assertEqual((c["project"]["in"], c["project"]["out"], c["project"]["cache_read"]), (10, 4, 1000))
        self.assertEqual(c["project"]["weighted"], 10 + 4 * 5 + 100 * 1.25 + 100)
        self.assertEqual(c["subagent"]["turns"], 1)
        self.assertEqual(c["brain"]["turns"], 3)
        self.assertEqual(d["total"]["turns"], 5)
        self.assertEqual(d["total"]["weighted"], sum(x["weighted"] for x in c.values()))

    def test_other_day_empty_and_bad_input(self):
        _write(f"{self.root}/-p/s.jsonl", _row("m", "r", self.ts))
        d = day_usage.collect_day("2001-01-01", self.root)
        self.assertEqual(d["total"]["turns"], 0)
        self.assertEqual(day_usage.collect_day(self.day, self.root + "/yok")["total"]["turns"], 0)
        with self.assertRaises(ValueError):
            day_usage.collect_day("bugun", self.root)

    def test_render(self):
        _write(f"{self.root}/-p/s.jsonl", _row("m", "r", self.ts, 3, 4))
        out = usage_cmd.render_day(day_usage.collect_day(self.day, self.root))
        self.assertIn("TOPLAM", out)
        self.assertIn("subagent", out)


if __name__ == "__main__":
    unittest.main()

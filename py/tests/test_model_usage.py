import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import model_usage as mu  # noqa: E402


def _line(model, ts, fresh=10, cw=100, read=1000, out=5):
    return json.dumps({"type": "assistant", "timestamp": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                       "message": {"model": model, "usage": {"input_tokens": fresh, "cache_creation_input_tokens": cw,
                                                             "cache_read_input_tokens": read, "output_tokens": out}}}) + "\n"


class ModelUsageTest(unittest.TestCase):
    def test_scan_counts_recent_calls_per_family_and_lists_fable_top(self):
        now = time.time()
        with tempfile.TemporaryDirectory() as d:
            proj = os.path.join(d, "-home-x-proj")
            os.makedirs(os.path.join(proj, "sess", "subagents"))
            with open(os.path.join(proj, "main.jsonl"), "w") as f:
                f.write(_line("claude-fable-5-1", now - 7200))              # pencere dışı
                f.write(_line("claude-fable-5-1", now - 600))
                f.write(_line("claude-sonnet-5-5", now - 300))
                f.write(json.dumps({"type": "user", "message": {"content": "x"}}) + "\n")
            with open(os.path.join(proj, "sess", "subagents", "agent-a1.jsonl"), "w") as f:
                f.write(_line("claude-fable-5-1", now - 100, cw=500, read=2000))
            with mock.patch.object(mu, "PROJECTS_DIR", d):
                r = mu.scan(minutes=60, now=now)
        self.assertEqual(r["families"]["fable"]["calls"], 2)
        self.assertEqual(r["families"]["fable"]["read"], 3000)
        self.assertEqual(r["families"]["fable"]["fresh"], 10 + 100 + 10 + 500)
        self.assertEqual(r["families"]["sonnet"]["calls"], 1)
        self.assertEqual(sorted(x["label"].endswith("(alt ajan)") for x in r["fable_top"]), [False, True])


if __name__ == "__main__":
    unittest.main()

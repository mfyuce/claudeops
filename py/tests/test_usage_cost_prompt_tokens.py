"""ucli'nin normalleştirilmiş `prompt_tokens`ı önbellek okuma+yazmayı İÇERİR: maliyet hesabı bunları bir de tam girdi
fiyatından saymaz (2 Kas 2026: günlük sayaç Console'dan ~5 kat şişkindi). Anthropic yerli `input_tokens` önbelleği içermez."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402


class UsageCost(unittest.TestCase):
    def _cost(self, usage):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "u.jsonl")
            with open(p, "w") as f:
                f.write(json.dumps({"event": "task_start", "model": "claude-sonnet-5-5", "t": 1}) + "\n")
                f.write(json.dumps({"event": "request", "t": 2, "usage": usage}) + "\n")
            return rv.usage_cost_usd(p, "")

    def test_prompt_tokens_includes_cache_not_double_counted(self):
        # sonnet-5-5: girdi 2.0, çıktı 10.0, okuma 0.10, yazma 2.5 ($/Mtok)
        c = self._cost({"prompt_tokens": 1_000_000, "cache_creation_input_tokens": 400_000,
                        "cache_read_input_tokens": 600_000, "completion_tokens": 0})
        self.assertAlmostEqual(c, 0.4 * 2.5 + 0.6 * 0.10, places=6)      # girdi payı 0

    def test_native_input_tokens_excludes_cache(self):
        c = self._cost({"input_tokens": 1_000_000, "cache_creation_input_tokens": 400_000,
                        "cache_read_input_tokens": 600_000, "output_tokens": 0})
        self.assertAlmostEqual(c, 1.0 * 2.0 + 0.4 * 2.5 + 0.6 * 0.10, places=6)


if __name__ == "__main__":
    unittest.main()

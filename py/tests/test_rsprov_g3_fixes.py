"""rs/prov G3 aday 3 ve 5 (TBD#383 kalıcı kuralı): transkript model/effort okuyucusu metin olmayan modeli ve alt ajan
(`isSidechain`) satırlarını oturumun değeri saymaz."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import claude_provider as cp  # noqa: E402


class _File(unittest.TestCase):
    def jsonl(self, *rows):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / "t.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path


def row(model, effort="high", **extra):
    return {"type": "assistant", "effort": effort, "message": {"model": model}, **extra}


class NonTextModelTest(_File):
    def test_non_text_model_is_skipped(self):
        for bad in (5, ["a"], {"a": 1}, True):
            with self.subTest(bad=bad):
                self.assertEqual(cp.last_assistant_model(self.jsonl(row("claude-opus-5-5"), row(bad))),
                                 "claude-opus-5-5")

    def test_only_non_text_model_means_unknown(self):
        self.assertIsNone(cp.last_assistant_model(self.jsonl(row(5))))


class SidechainTest(_File):
    def test_sub_agent_rows_do_not_set_model_or_effort(self):
        path = self.jsonl(row("claude-sonnet-5-5", "medium"),
                          row("claude-opus-5-5", "max", isSidechain=True))
        self.assertEqual(cp.last_assistant_model(path), "claude-sonnet-5-5")
        self.assertEqual(cp.last_assistant_effort(path), "medium")

    def test_only_sub_agent_rows_mean_unknown(self):
        path = self.jsonl(row("claude-opus-5-5", "max", isSidechain=True))
        self.assertIsNone(cp.last_assistant_model(path))
        self.assertIsNone(cp.last_assistant_effort(path))

    def test_false_flag_counts(self):
        path = self.jsonl(row("claude-opus-5-5", "max", isSidechain=False))
        self.assertEqual(cp.last_assistant_model(path), "claude-opus-5-5")
        self.assertEqual(cp.last_assistant_effort(path), "max")


if __name__ == "__main__":
    unittest.main()

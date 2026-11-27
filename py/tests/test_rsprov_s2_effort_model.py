"""rs/prov S2 (sahip onayı (a), 27 Kas): canlı effort yalnız son yanıt satırıyla AYNI modele ait satırlardan alınır;
model değiştiyse eski effort taşınmaz (okuyan açılış değerine düşer). Hepsi geçici dosya."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import claude_provider as cp  # noqa: E402

A, B = "claude-sonnet-5-5", "claude-haiku-5-5"


def row(model=None, effort=None, **extra):
    out = {"type": "assistant", **extra}
    if model is not None:
        out["message"] = {"model": model}
    if effort is not None:
        out["effort"] = effort
    return out


class EffortFollowsTheModelTest(unittest.TestCase):
    def jsonl(self, *rows):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / "s.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path

    def effort(self, *rows):
        return cp.last_assistant_effort(self.jsonl(*rows))

    def test_effort_of_the_previous_model_is_not_carried_over(self):
        self.assertIsNone(self.effort(row(A, "max"), row(B)))

    def test_same_model_keeps_the_older_effort(self):
        self.assertEqual(self.effort(row(B, "low"), row(A, "max"), row(A)), "max")

    def test_scan_stops_at_a_model_change_even_if_the_model_returns(self):
        self.assertIsNone(self.effort(row(A, "max"), row(B, "low"), row(A)))

    def test_rows_without_a_real_model_neither_give_nor_stop(self):
        skipped = [row(effort="low"), row("<synthetic>", "low"), row(B, "low", isSidechain=True), row("", "low")]
        self.assertEqual(self.effort(row(A, "max"), *skipped), "max")
        self.assertEqual(self.effort(row(A, "max"), row(B, "low", isSidechain=True), row(A)), "max")

    def test_no_answer_row_with_a_model_means_unknown(self):
        self.assertIsNone(self.effort(row(effort="low")))

    def test_the_rule_holds_across_the_growing_window(self):
        pad = [{"type": "user", "pad": "x" * 1000}] * 100        # > ilk pencere (64 KiB)
        self.assertIsNone(self.effort(row(A, "max"), *pad, row(B)))
        self.assertEqual(self.effort(row(A, "max"), *pad, row(A)), "max")

    def test_live_or_spawn_falls_back_to_the_spawn_effort(self):
        path = self.jsonl(row(A, "max"), row(B))
        with mock.patch.object(cp, "jsonl_path_for", lambda cwd, sid: path):
            self.assertEqual(cp.live_or_spawn_effort("claude", "/w", "s", "spawn-e"), "spawn-e")
            self.assertEqual(cp.live_or_spawn_model("claude", "/w", "s", "spawn-m"), B)


if __name__ == "__main__":
    unittest.main()

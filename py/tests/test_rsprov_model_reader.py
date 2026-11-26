"""TBD#386: transkriptten model okuyucu `<synthetic>` yer tutucusunu ve nesne olmayan satır/`message`i atlar.

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_model_reader.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import claude_provider as cp  # noqa: E402


def _row(message, **extra):
    return json.dumps(dict({"type": "assistant", "message": message, "timestamp": "2026-11-26T10:00:00Z"}, **extra))


REAL = _row({"model": "claude-opus-5-5"}, effort="high")


class ModelReaderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "s.jsonl"

    def _write(self, *rows):
        self.path.write_text("".join(r + "\n" for r in rows), encoding="utf-8")
        return self.path

    def test_synthetic_placeholder_is_skipped(self):
        self.assertEqual(cp.last_assistant_model(self._write(REAL, _row({"model": "<synthetic>"}))), "claude-opus-5-5")

    def test_only_synthetic_means_unknown(self):
        self.assertIsNone(cp.last_assistant_model(self._write(_row({"model": "<synthetic>"}))))

    def test_stuck_recovery_value_is_the_real_model(self):
        self._write(REAL, _row({"model": "<synthetic>"}))
        with mock.patch.object(cp, "jsonl_path_for", return_value=self.path):
            self.assertEqual(cp.live_or_spawn_model("claude", "/x", "s", "spawn"), "claude-opus-5-5")

    def test_non_object_message_is_skipped(self):
        for bad in ("x", 5, [1], None, True):
            with self.subTest(message=bad):
                path = self._write(REAL, _row(bad))
                self.assertEqual(cp.last_assistant_model(path), "claude-opus-5-5")

    def test_non_object_line_is_skipped(self):
        for bad in ("5", '"x"', "[1]", "null", "true"):
            with self.subTest(line=bad):
                path = self._write(REAL, bad)
                self.assertEqual(cp.last_assistant_model(path), "claude-opus-5-5")
                self.assertEqual(cp.last_assistant_effort(path), "high")
                self.assertIsNone(cp.last_real_request_epoch(path))

    def test_since_still_stops_at_older_row(self):
        path = self._write(REAL, _row({"model": "<synthetic>"}, timestamp="2026-11-26T12:00:00Z"))
        since = cp._row_epoch("2026-11-26T11:00:00Z")
        self.assertIsNone(cp.last_assistant_model(path, since=since))


if __name__ == "__main__":
    unittest.main()

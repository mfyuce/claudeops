"""TBD#386: transkriptten model okuyucu nesne olmayan satır/`message`i atlar.

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_model_reader.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

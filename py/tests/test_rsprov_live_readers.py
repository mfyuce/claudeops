"""Canlı durum okuyucuları (rs/prov G6): tek bozuk girdi taramayı düşürmez, uydurma sayı dönmez.

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_live_readers.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import bg_work, settings, ucli_client  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402

NOW = 1795428000.0
TS = "2026-11-23T10:00:00Z"
DEEP = '{"x":"background SubAgentActivity","d":' + "[" * 100000 + "]" * 100000 + "}"
USE = json.dumps({"timestamp": TS, "message": {"content": [
    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"run_in_background": True}}]}})
AGENT = json.dumps({"timestamp": TS, "payload": {"item": {
    "type": "SubAgentActivity", "kind": "started", "agent_thread_id": "a1"}}})


class BadLineTest(unittest.TestCase):
    def setUp(self):
        self.now = bg_work._epoch(TS) + 60

    def test_claude_one_bad_line_does_not_drop_the_scan(self):
        bad = ('"background"', '["background"]', '{"message":"background"}', '{"message":["background"]}',
               '{"message":{"content":[{"type":"tool_use","id":"z","input":"background"}]}}',
               '{"message":{"content":[{"type":"tool_use","id":["z"],"input":{"run_in_background":true}}]}}',
               '{"message":{"content":[{"type":"tool_use","id":{"a":1},"input":{"run_in_background":true}}]}}',
               '{"message":{"content":[{"type":"tool_result","tool_use_id":["z"],"x":"background"}]}}', DEEP)
        for line in bad:
            for rows in ([line, USE], [USE, line]):
                with self.subTest(line=line[:60]):
                    self.assertTrue(bg_work.transcript_pending(rows, self.now))
            with self.subTest(alone=line[:60]):
                self.assertFalse(bg_work.transcript_pending([line], self.now))

    def test_codex_one_bad_line_does_not_drop_the_scan(self):
        bad = ('"SubAgentActivity"', '["SubAgentActivity"]', '{"payload":"SubAgentActivity"}',
               '{"payload":{"item":"SubAgentActivity"}}', '{"payload":["SubAgentActivity"]}', DEEP)
        for line in bad:
            for rows in ([line, AGENT], [AGENT, line]):
                with self.subTest(line=line[:60]):
                    self.assertEqual(bg_work.codex_subagents_pending(rows, self.now), 1)

class UcliBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cwd = tmp.name
        self.chat = Path(tmp.name) / ".ucli" / "chat"
        (self.chat / "failed").mkdir(parents=True)
        for patch in (mock.patch.object(settings, "ucli_state_dir_enabled", return_value=False),
                      mock.patch.object(ucli_client, "state_dir_for", return_value=os.path.join(tmp.name, "yok"))):
            patch.start()
            self.addCleanup(patch.stop)


class FailedRecordNameTest(UcliBase):
    def test_a_superscript_digit_name_does_not_hide_the_records(self):
        for name in ("s-5-1.json", "s-²-1.json", "s-6-².json", "s-①-1.json"):
            (self.chat / "failed" / name).write_text('{"error":"x"}', encoding="utf-8")
        self.assertEqual([u for u, _p in ucli_client.failed_turn_records(self.cwd, "s")], [5])
        self.assertEqual(up.UcliProvider().live_failed_turns(self.cwd, "s"), {"count": 1, "last_unix": 5, "last_error": "x"})


if __name__ == "__main__":
    unittest.main()

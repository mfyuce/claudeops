"""Canlı durum okuyucuları (rs/prov G6): tek bozuk girdi taramayı düşürmez, uydurma sayı dönmez.

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_live_readers.py
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import bg_work, settings, ucli_client  # noqa: E402
from claudeops.providers import codex_provider as xp  # noqa: E402
from claudeops.providers import copilot_provider as cop  # noqa: E402
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
               '{"message":{"content":[{"type":"tool_result","tool_use_id":["z"],"x":"background"}]}}',
               '{"message":{"content":[{"type":"tool_use","id":"z","name":["TaskStop"],"x":"background"}]}}',
               '{"message":{"content":[{"type":"tool_use","id":"z","name":"TaskStop","input":"b1"}]}}',
               '{"message":{"content":[{"type":"tool_use","id":["z"],"name":"TaskStop","input":{}}]}}', DEEP)
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

class StatusFileTest(UcliBase):
    BODIES = ('{"activity":"x","n":' + "9" * 5000 + "}", '{"d":' + "[" * 100000 + "]" * 100000 + "}")

    def test_huge_number_or_deep_document_means_unreadable(self):
        p = up.UcliProvider()
        for body in self.BODIES:
            with self.subTest(body=body[:30]):
                (self.chat / "s.status.json").write_text(body, encoding="utf-8")
                self.assertIsNone(ucli_client.read_status_file(self.cwd, "s"))
                self.assertIsNone(p.live_busy(self.cwd, "s"))
                self.assertIsNone(p.live_usage(self.cwd, "s"))
                self.assertIsNone(p.live_phase(self.cwd, "s"))

    def test_deep_or_huge_failed_record_keeps_the_count(self):
        for body in self.BODIES:
            with self.subTest(body=body[:30]):
                (self.chat / "failed" / "s-5-1.json").write_text(body, encoding="utf-8")
                self.assertEqual(up.UcliProvider().live_failed_turns(self.cwd, "s"), {"count": 1, "last_unix": 5})

def _token_count(value):
    return json.dumps({"type": "event_msg", "payload": {"type": "token_count",
                                                         "info": {"last_token_usage": {"input_tokens": value}}}})


class CodexContextTest(unittest.TestCase):
    def context(self, *rows):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "r.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write("".join(r + "\n" for r in rows))
            with mock.patch.object(xp.CodexProvider, "_rollout_path", return_value=path):
                return xp.CodexProvider().live_context("/x", "s")

    def test_boolean_and_negative_counts_are_skipped(self):
        for bad in (True, False, -5):
            with self.subTest(bad=bad):
                self.assertEqual(self.context(_token_count(7), _token_count(bad)), 7)
                self.assertIsNone(self.context(_token_count(bad)))

    def test_zero_still_means_unknown(self):
        self.assertIsNone(self.context(_token_count(7), _token_count(0)))

    def test_deep_line_is_skipped(self):
        deep = '{"x":"token_count","d":' + "[" * 100000 + "]" * 100000 + "}"
        deep = deep.replace('"x":"token_count"', '"token_count":1')
        self.assertEqual(self.context(_token_count(7), deep), 7)

class CopilotContextTest(unittest.TestCase):
    def context(self, value):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.db")
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE assistant_usage_events (session_id TEXT, turn_index INT, agent_id TEXT, "
                       "input_tokens, created_at TEXT)")
            db.execute("INSERT INTO assistant_usage_events VALUES ('s', 0, NULL, ?, 't')", (value,))
            db.commit()
            db.close()
            with mock.patch.object(cop, "SESSION_STORE_DB", path):
                return cop.CopilotProvider().live_context("/x", "s")

    def test_non_number_means_unknown(self):
        for value in ("abc", "", "1.5", float("inf"), float("-inf"), b"x"):
            with self.subTest(value=value):
                self.assertIsNone(self.context(value))

    def test_numbers_still_work(self):
        self.assertEqual(self.context(12), 12)
        self.assertEqual(self.context(" 1_000 "), 1000)
        self.assertEqual(self.context(1234.9), 1234)

class ListToolResultTest(unittest.TestCase):
    def rows(self, content, done="bg7"):
        result = json.dumps({"message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": content}]},
                             "x": "background"})
        notif = json.dumps({"message": {"content": "<task-notification><task-id>" + done +
                                        "</task-id><status>completed</status></task-notification>"}})
        return [USE, result, notif]

    def test_id_at_line_start_is_found_in_list_content(self):
        now = bg_work._epoch(TS) + 60
        for content in ([{"type": "text", "text": "Command running in background.\nID: bg7"}],
                        [{"type": "text", "text": "ID: bg7"}],
                        [{"type": "text", "text": "Basladi"}, {"type": "text", "text": "ID: bg7"}],
                        [5, {"type": "text", "text": 5}, {"type": "text", "text": "ID: bg7"}],
                        "Command running in background.\nID: bg7"):
            with self.subTest(content=content):
                self.assertFalse(bg_work.transcript_pending(self.rows(content), now))
                self.assertTrue(bg_work.transcript_pending(self.rows(content, done="baska"), now))

    def test_non_text_blocks_do_not_supply_an_id(self):
        now = bg_work._epoch(TS) + 60
        rows = self.rows([{"type": "image", "source": "ID: bg7"}])
        self.assertTrue(bg_work.transcript_pending(rows, now))


if __name__ == "__main__":
    unittest.main()

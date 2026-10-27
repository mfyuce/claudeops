"""`CliProvider.live_context`: tmux-pane CLI'larda (codex, copilot) bağlam boyutu yapılandırılmış dosyadan; bilinmeyen = None
(0 DEĞİL). Gerçek ~/.codex / ~/.copilot'a dokunmaz: yollar geçici dizine yönlendirilir."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import codex_provider as cx, copilot_provider as cp, get_provider  # noqa: E402
from claudeops.providers.base import CliProvider  # noqa: E402


def _tc(inp, cached=0):
    return json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
        "last_token_usage": {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": 5},
        "total_token_usage": {"input_tokens": inp * 3}, "model_context_window": 258400}}})


class TestBase(unittest.TestCase):
    def test_default_and_unsupported_are_none(self):
        self.assertIsNone(CliProvider.live_context(get_provider("agy"), "/x", "sid"))
        self.assertIsNone(get_provider("shell").live_context("/x", None))


class TestCodex(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        day = os.path.join(self.d.name, "2026", "10", "27")
        os.makedirs(day)
        self.path = os.path.join(day, "rollout-x-sidabc.jsonl")
        p = mock.patch.object(cx, "SESSIONS_DIR", self.d.name)
        p.start()
        self.addCleanup(p.stop)

    def write(self, *lines):
        with open(self.path, "w") as f:
            f.write("\n".join(lines) + "\n")

    def test_last_token_count_input_tokens(self):
        self.write(_tc(1000, 900), '{"type":"response_item","payload":{}}', _tc(20138, 19456))
        self.assertEqual(get_provider("codex").live_context("/w", "sidabc"), 20138)   # cached ayrıca EKLENMEZ (çift sayım)

    def test_no_token_event_or_no_file_is_none(self):
        self.write('{"type":"response_item","payload":{}}')
        self.assertIsNone(get_provider("codex").live_context("/w", "sidabc"))
        self.assertIsNone(get_provider("codex").live_context("/w", "yok-sid"))

    def test_null_info_is_none(self):
        self.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": None}}))
        self.assertIsNone(get_provider("codex").live_context("/w", "sidabc"))


class TestCopilot(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.db = os.path.join(self.d.name, "s.db")
        c = sqlite3.connect(self.db)
        c.execute("CREATE TABLE assistant_usage_events (session_id TEXT, turn_index INT, agent_id TEXT, input_tokens INT, created_at TEXT)")
        c.executemany("INSERT INTO assistant_usage_events VALUES (?,?,?,?,?)", [
            ("s1", 0, None, 1000, "2026-10-27T10:00:00Z"),
            ("s1", 1, None, 5000, "2026-10-27T10:05:00Z"),
            ("s1", 1, "sub1", 99999, "2026-10-27T10:06:00Z"),     # alt ajan: sayılmaz
            ("s2", 0, None, 7, "2026-10-27T10:07:00Z")])
        c.commit()
        c.close()
        p = mock.patch.object(cp, "SESSION_STORE_DB", self.db)
        p.start()
        self.addCleanup(p.stop)

    def test_latest_main_agent_row(self):
        self.assertEqual(get_provider("copilot").live_context("/w", "s1"), 5000)

    def test_unknown_session_or_no_db_is_none(self):
        self.assertIsNone(get_provider("copilot").live_context("/w", "yok"))
        with mock.patch.object(cp, "SESSION_STORE_DB", os.path.join(self.d.name, "nope.db")):
            self.assertIsNone(get_provider("copilot").live_context("/w", "s1"))


if __name__ == "__main__":
    unittest.main()


class TestStatusRow(unittest.TestCase):
    def test_context_info_uses_provider_hook_and_hides_unknown(self):
        from types import SimpleNamespace as NS
        from claudeops.commands import web
        web._CTXINFO_CACHE.clear()
        self.addCleanup(web._CTXINFO_CACHE.clear)
        s = NS(name="cx1", pid=11, cli="codex", cwd="/w", sid="abc", model="gpt-5")
        with mock.patch.object(cx.CodexProvider, "live_context", lambda self, c, i: 42000):
            self.assertEqual(web._context_info_cached(s)["tokens"], 42000)
        web._CTXINFO_CACHE.clear()
        with mock.patch.object(cx.CodexProvider, "live_context", lambda self, c, i: None):
            self.assertIsNone(web._context_info_cached(s))
        self.assertIsNone(web._context_info_cached(NS(name="sh", pid=12, cli="shell", cwd="/w", sid=None, model="")))

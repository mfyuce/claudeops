"""`web._live_snapshot_entries` testleri (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_snapshot_live_entries.py -v

Kapsadığı hata (TODO.md 2026-10-09): snapshot, session'ların `--model`/`--effort` cmdline
(SPAWN-ANI) değerini kaydediyordu; canlıda `/model` ile 5.5'e geçirilen session'lar resume'da
yine eski modelle (sonnet 5) başlıyordu. Gerçek session'lara / dosyalara DOKUNMAZ.
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402


def sess(name, cli="claude", sid="sid-1", model="claude-sonnet-5", effort="max", cwd="/w/p"):
    return SimpleNamespace(name=name, cli=cli, sid=sid, model=model, effort=effort, cwd=cwd,
                           permission_mode="auto")


def exact_jsonl(cwd, sid):
    return Path(f"/projects/x/{sid}.jsonl") if sid else None


class LiveSnapshotEntriesTests(unittest.TestCase):
    def run_entries(self, sessions, jsonl_for=exact_jsonl, live_model=lambda p: None,
                    live_effort=lambda p: None):
        with mock.patch.object(web, "find_sessions", lambda measure_cpu=False: sessions), \
             mock.patch.object(web, "jsonl_path_for", jsonl_for), \
             mock.patch.object(web, "last_assistant_model", live_model), \
             mock.patch.object(web, "last_assistant_effort", live_effort):
            return web._live_snapshot_entries()

    def test_live_model_and_effort_replace_spawn_time_values(self):
        out = self.run_entries([sess("vc20261008", model="claude-haiku-5-5")],
                               live_model=lambda p: "claude-sonnet-5-5", live_effort=lambda p: "high")
        self.assertEqual(out, [{"name": "vc20261008", "cwd": "/w/p", "model": "claude-sonnet-5-5",
                                "permission_mode": "auto", "effort": "high", "cli": "claude"}])

    def test_no_assistant_turn_yet_keeps_spawn_time_values(self):
        out = self.run_entries([sess("a")])  # live_* None döner
        self.assertEqual((out[0]["model"], out[0]["effort"]), ("claude-sonnet-5", "max"))

    def test_session_without_sid_is_not_looked_up(self):
        calls = []

        def jsonl_for(cwd, sid):
            calls.append(sid)
            return Path("/projects/x/other-session.jsonl")

        out = self.run_entries([sess("a", sid=None)], jsonl_for=jsonl_for,
                               live_model=lambda p: "claude-opus-5-5")
        self.assertEqual(calls, [])
        self.assertEqual(out[0]["model"], "claude-sonnet-5")

    def test_mtime_fallback_to_another_sessions_file_is_ignored(self):
        """jsonl_path_for, sid'in dosyası yoksa cwd'deki EN SON jsonl'a düşer: başka bir
        session'ın modeli bu snapshot girdisine yazılmamalı."""
        out = self.run_entries([sess("a", sid="mine")],
                               jsonl_for=lambda cwd, sid: Path("/projects/x/someone-else.jsonl"),
                               live_model=lambda p: "claude-opus-5-5", live_effort=lambda p: "low")
        self.assertEqual((out[0]["model"], out[0]["effort"]), ("claude-sonnet-5", "max"))

    def test_non_claude_session_is_untouched(self):
        called = []
        out = self.run_entries([sess("g", cli="agy", model="gemini-3.1-pro-high", effort=None)],
                               jsonl_for=lambda cwd, sid: called.append(sid),
                               live_model=lambda p: "claude-opus-5-5")
        self.assertEqual(called, [])
        self.assertEqual((out[0]["model"], out[0]["effort"], out[0]["cli"]), ("gemini-3.1-pro-high", None, "agy"))

    def test_helper_failure_falls_back_to_spawn_time_and_does_not_raise(self):
        def boom(p):
            raise OSError("jsonl okunamadı")

        out = self.run_entries([sess("a"), sess("b", sid="sid-2")], live_model=boom)
        self.assertEqual([(e["name"], e["model"]) for e in out],
                         [("a", "claude-sonnet-5"), ("b", "claude-sonnet-5")])

    def test_model_live_but_effort_failure_keeps_live_model(self):
        def boom(p):
            raise OSError("effort okunamadı")

        out = self.run_entries([sess("a")], live_model=lambda p: "claude-sonnet-5-5", live_effort=boom)
        self.assertEqual((out[0]["model"], out[0]["effort"]), ("claude-sonnet-5-5", "max"))


if __name__ == "__main__":
    unittest.main()

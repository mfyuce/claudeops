"""Arka plan işi = meşgul (23 Kas, derbent): ekran işaretleri + transkriptte bildirimi gelmemiş run_in_background."""
import calendar
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from claudeops import bg_work
from claudeops.commands import web_steward

SCREEN_SHELL = """\
· Churning… (8s · ↓ 277 tokens)
────────────────────────────── derbent ─
❯
  ⏵⏵ auto mode on · 1 shell · esc to interrupt · ← 1 agent · ↓ to manage       /rc

● main
○ general-purpose  waiting on 1 shell · Yol öneki rewrite (köke göreli) · since 18:08
"""
SCREEN_BG_TASKS = """\
❯
  2 background tasks · ← 1 agent · ↓ to manage
"""
SCREEN_OWN_WORK = """\
● main
○ general-purpose  Agent is waiting on its own background work · 40m
"""
SCREEN_IDLE = """\
● Bitti: 3 agents tamamlandı, 2 shells kapandı.
❯
  ⏵⏵ auto mode on · ? for shortcuts
"""


class ScreenFixture(unittest.TestCase):
    def test_busy_screens(self):
        for s in (SCREEN_SHELL, SCREEN_BG_TASKS, SCREEN_OWN_WORK):
            self.assertTrue(bg_work.screen_bg_work(s), s)

    def test_idle_screen_with_prose_numbers(self):
        self.assertFalse(bg_work.screen_bg_work(SCREEN_IDLE))
        self.assertFalse(bg_work.screen_bg_work(""))
        self.assertFalse(bg_work.screen_bg_work("0 background tasks · ↓ to manage"))


def _use(i, bg=True, ts="2026-11-23T10:00:00Z"):
    return json.dumps({"timestamp": ts, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": i, "name": "Bash", "input": {"command": "x", "run_in_background": bg}}]}})


def _res(i, task):
    return json.dumps({"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": i, "content": f"Command running in background with ID: {task}."}]}})


def _notif(status, i=None, task=None):
    body = "<task-notification>" + (f"<task-id>{task}</task-id>" if task else "") + (f"<tool-use-id>{i}</tool-use-id>" if i else "") \
        + f"<status>{status}</status></task-notification>"
    return json.dumps({"message": {"role": "user", "content": body}})


T = calendar.timegm(time.strptime("2026-11-23T10:30:00", "%Y-%m-%dT%H:%M:%S"))


class TranscriptFixture(unittest.TestCase):
    def test_pending_without_notification(self):
        self.assertTrue(bg_work.transcript_pending([_use("t1"), _res("t1", "b1")], now=T))

    def test_completed_by_tool_use_id_or_task_id(self):
        for status in ("completed", "failed", "killed"):
            self.assertFalse(bg_work.transcript_pending([_use("t1"), _notif(status, i="t1")], now=T), status)
        self.assertFalse(bg_work.transcript_pending([_use("t1"), _res("t1", "b1"), _notif("completed", task="b1")], now=T))

    def test_foreground_and_stale(self):
        self.assertFalse(bg_work.transcript_pending([_use("t1", bg=False)], now=T))
        self.assertFalse(bg_work.transcript_pending([_use("t1")], now=T + 7 * 3600))

    def test_one_of_two_pending(self):
        self.assertTrue(bg_work.transcript_pending([_use("t1"), _use("t2"), _notif("completed", i="t1")], now=T))


class SubagentActiveForUsesBoth(unittest.TestCase):
    def test_screen_makes_active_even_without_subagent_files(self):
        with mock.patch.object(web_steward, "tmux_capture", return_value=SCREEN_SHELL):
            self.assertTrue(web_steward.subagent_active_for("/nonexistent", None, name="derbent"))
        with mock.patch.object(web_steward, "tmux_capture", return_value=SCREEN_IDLE):
            self.assertFalse(web_steward.subagent_active_for("/nonexistent", None, name="derbent"))

    def test_transcript_pending_makes_active(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "s.jsonl")
        with open(p, "w") as f:
            f.write(_use("t1", ts="2099-01-01T00:00:00Z") + "\n")
        with mock.patch("claudeops.providers.claude_provider.jsonl_path_for", return_value=p), \
             mock.patch.object(web_steward, "tmux_capture", return_value=""):
            self.assertTrue(web_steward.subagent_active_for("/x", "sid", name="n"))


if __name__ == "__main__":
    unittest.main()


class ProviderBackgroundWork(unittest.TestCase):
    def test_base_unknown_and_claude_counts(self):
        from claudeops.providers import PROVIDERS
        for n, p in PROVIDERS.items():
            if n != "claude":
                self.assertIsNone(p.background_work("1 shell · esc to interrupt", "/x", None), n)
        c = PROVIDERS["claude"]
        self.assertEqual(c.background_work(SCREEN_BG_TASKS, "/nonexistent", None), 3)
        self.assertEqual(c.background_work(SCREEN_SHELL, "/nonexistent", None), 2)
        self.assertEqual(c.background_work(SCREEN_OWN_WORK, "/nonexistent", None), 1)
        self.assertEqual(c.background_work(SCREEN_IDLE, "/nonexistent", None), 0)


class UcliBackgroundWork(unittest.TestCase):
    def test_reads_status_field_never_guesses(self):
        from claudeops.providers import PROVIDERS
        u = PROVIDERS["ucli"]
        with mock.patch("claudeops.providers.ucli_provider.read_status_file", return_value={"activity": "waiting_for_stdin", "background_tasks": 2}):
            self.assertEqual(u.background_work("", "/x", "s"), 2)
        for st in ({"activity": "waiting_for_stdin"}, {"background_tasks": "2"}, {"background_tasks": -1}, {"background_tasks": True}, None):
            with mock.patch("claudeops.providers.ucli_provider.read_status_file", return_value=st):
                self.assertIsNone(u.background_work("", "/x", "s"), st)
        self.assertIsNone(u.background_work("", "/x", None))

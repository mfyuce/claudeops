"""Arka plan işi = meşgul (23 Kas, derbent): ekran işaretleri + transkriptte bildirimi gelmemiş run_in_background."""
import calendar
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from claudeops import bg_work, paths
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

    def test_errored_call_is_not_pending(self):
        err = json.dumps({"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "Permission denied."}]}})
        self.assertFalse(bg_work.transcript_pending([_use("t1"), err], now=T))
        self.assertTrue(bg_work.transcript_pending([_use("t1"), _use("t2"), err], now=T))

    def test_one_of_two_pending(self):
        self.assertTrue(bg_work.transcript_pending([_use("t1"), _use("t2"), _notif("completed", i="t1")], now=T))


def _stop(use_id, target, tool="TaskStop", key="task_id", error=False):
    res = {"type": "tool_result", "tool_use_id": use_id,
           "content": "No task found" if error else json.dumps({"message": f"Successfully stopped task: {target} (x)", "task_id": target})}
    if error:
        res["is_error"] = True
    return [json.dumps({"message": {"role": "assistant", "content": [{"type": "tool_use", "id": use_id, "name": tool, "input": {key: target}}]}}),
            json.dumps({"message": {"role": "user", "content": [res]}})]


class StoppedAndMidTurnNotifications(unittest.TestCase):
    """27 Kas, copsdev: TaskStop ile durdurulan iş bildirim üretmedi; alt ajan bittiği hâlde direktif 6 sa `subagent_active` diye ertelendi.
    Tur ortasında gelen bildirim de `user` satırı değil, `queue-operation` / `attachment` kaydıdır (aynı transkriptten)."""
    BODY = "<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>t1</tool-use-id>\n<status>completed</status>\n</task-notification>"

    def test_stopped_task_is_not_pending(self):
        for tool, key in (("TaskStop", "task_id"), ("TaskStop", "shell_id"), ("KillShell", "shell_id")):
            lines = [_use("t1"), _res("t1", "b1"), *_stop("s1", "b1", tool, key)]
            self.assertFalse(bg_work.transcript_pending(lines, now=T), (tool, key))

    def test_failed_stop_or_other_task_stays_pending(self):
        self.assertTrue(bg_work.transcript_pending([_use("t1"), _res("t1", "b1"), *_stop("s1", "b1", error=True)], now=T))
        self.assertTrue(bg_work.transcript_pending([_use("t1"), _res("t1", "b1"), *_stop("s1", "b2")], now=T))
        self.assertTrue(bg_work.transcript_pending([_use("t1"), _res("t1", "b1"), _stop("s1", "b1")[0]], now=T))   # sonuç henüz yok

    def test_notification_delivered_mid_turn(self):
        queued = json.dumps({"type": "queue-operation", "operation": "enqueue", "content": self.BODY})
        attached = json.dumps({"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "task-notification", "prompt": self.BODY}})
        for rec in (queued, attached):
            self.assertFalse(bg_work.transcript_pending([_use("t1"), _res("t1", "b1"), rec], now=T), rec)

    def test_quoted_notification_in_queued_user_text_does_not_count(self):
        quoted = "şu bildirimi gördün mü: " + self.BODY
        for rec in (json.dumps({"type": "queue-operation", "operation": "enqueue", "content": quoted}),
                    json.dumps({"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt", "prompt": self.BODY}})):
            self.assertTrue(bg_work.transcript_pending([_use("t1"), _res("t1", "b1"), rec], now=T), rec)


class NavigationHintAndRequestCopies(unittest.TestCase):
    """27 Kas, copsdev: reddedilen arka plan çağrısının `api-request-blob` kopyası işi yeniden "bekliyor" yapıyordu (zaman damgası
    olmadığı için hiç eskimiyordu; direktif iletilemedi). Alt satırdaki `← N agent` gezinme ipucudur, iş sayısı değil."""
    IDLE = "❯\n  ⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent                               /rc\n"
    TURN = "❯\n  ⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt · ← 1 agent            /rc\n"

    def test_agent_view_hint_is_not_background_work(self):
        for s in (self.IDLE, self.TURN, self.TURN.replace("← 1 agent", "← 3 agents"), "  ← 2 agents · ↓ to manage"):
            self.assertEqual((bg_work.screen_bg_count(s), bg_work.screen_bg_work(s)), (0, False), s)

    def test_real_counts_beside_the_hint_still_count(self):
        self.assertEqual(bg_work.screen_bg_count("  ⏵⏵ auto mode on · 1 shell · ← 1 agent · ↓ to manage"), 1)
        self.assertEqual(bg_work.screen_bg_count(SCREEN_BG_TASKS), 2)
        self.assertEqual(bg_work.screen_bg_count("  2 agents · ↓ to manage"), 2)

    @staticmethod
    def _typed(rec, kind):
        return json.dumps({"type": kind, **json.loads(rec)})

    def _blob(self, i):
        o = json.loads(_use(i))
        return json.dumps({"type": "api-request-blob", "hash": "h", "sessionId": "s", "message": o["message"]})

    def test_request_copy_does_not_revive_refused_call(self):
        err = json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "no verdict"}]}})
        self.assertFalse(bg_work.transcript_pending([self._typed(_use("t1"), "assistant"), err, self._blob("t1")], now=T))

    def test_request_copy_alone_is_not_a_job(self):
        self.assertFalse(bg_work.transcript_pending([self._blob("t9")], now=T))

    def test_typed_assistant_record_is_still_pending_and_expires(self):
        lines = [self._typed(_use("t1"), "assistant"), self._blob("t1")]
        self.assertTrue(bg_work.transcript_pending(lines, now=T))
        self.assertFalse(bg_work.transcript_pending(lines, now=T + 7 * 3600))


# Canlı claude 2.1.332 alt satırları (27 Kas 23:49, 20 oturum): (süreç kaydı `status`, alt satır, ekranda iş sayısı, çalışan iş var mı)
LIVE_FOOTERS = (
    ("idle", "⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent                               /rc", 0, False),
    ("idle", "⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent", 0, False),
    ("idle", "⏵⏵ auto mode on (shift+tab to cycle)        new task? /clear to save 177.9k tokens", 0, False),
    ("shell", "⏵⏵ auto mode on · 1 shell · ← 1 agent · ↓ to manage                            /rc", 1, True),
    ("busy", "⏵⏵ auto mode on · 3 background tasks · ← 1 agent · ↓ to manage                 /rc", 3, True),
    ("busy", "⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent · ↓ to manage                 /rc", 0, True),   # yalnız alt ajan
    ("busy", "⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt · ← 1 agent            /rc", 0, True),   # ana tur
)


class SessionRecordSignal(unittest.TestCase):
    """claude süreç kaydı (`sessions/<pid>.json`): `busy` = tur ya da devredilen ajan, `shell` = tur bitti, kabuk/Monitor açık."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        p = mock.patch.object(paths, "SESSIONS_DIR", d.name)
        p.start()
        self.addCleanup(p.stop)

    def record(self, status, sid="s1", pid=None, start=None):
        pid = os.getpid() if pid is None else pid
        with open(f"/proc/{os.getpid()}/stat") as f:
            mine = f.read().rsplit(")", 1)[1].split()[19]
        with open(os.path.join(self.dir, f"{pid}.json"), "w") as f:
            json.dump({"pid": pid, "sessionId": sid, "status": status, "procStart": start or mine}, f)

    def work(self, footer, sid="s1"):
        from claudeops.providers import PROVIDERS
        return PROVIDERS["claude"].background_work("❯\n  " + footer + "\n", "/nonexistent", sid)

    def test_live_footers(self):
        for status, footer, screen, active in LIVE_FOOTERS:
            self.assertEqual(bg_work.screen_bg_count(footer), screen, footer)
            self.record(status)
            self.assertEqual(self.work(footer) > 0, active, (status, footer))

    def test_record_of_dead_reused_or_other_session_is_ignored(self):
        idle = LIVE_FOOTERS[0][1]
        self.record("busy", sid="baska")
        self.assertEqual(self.work(idle), 0)
        self.record("shell", start="1")          # pid yeniden kullanılmış: başlangıç anı tutmuyor
        self.assertEqual(self.work(idle), 0)
        self.record("shell", pid=2 ** 22 + 7)    # süreç yok
        self.assertEqual(self.work(idle), 0)

    def pending_work(self):
        """Ekran boş, transkriptte bildirimi gelmemiş arka plan işi var: `background_work` ne diyor."""
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = os.path.join(d.name, "s.jsonl")
        with open(p, "w") as f:
            f.write(_use("t1", ts="2099-01-01T00:00:00Z") + "\n")
        with mock.patch("claudeops.providers.claude_provider.jsonl_path_for", return_value=Path(p)):
            return self.work(LIVE_FOOTERS[0][1])

    def test_idle_record_overrides_transcript_history(self):
        self.record("idle")
        self.assertEqual(self.pending_work(), 0)

    def test_idle_record_does_not_hide_the_screen_counter(self):
        self.record("idle")
        self.assertGreater(self.work("⏵⏵ auto mode on · 1 shell · ↓ to manage"), 0)

    def test_transcript_still_used_when_record_cannot_decide(self):
        self.assertEqual(self.pending_work(), 1)              # kayıt yok
        for kw in ({"status": "waiting"}, {"status": "yeni-durum"}, {"status": "idle", "sid": "baska"},
                   {"status": "idle", "start": "1"}, {"status": "idle", "pid": 2 ** 22 + 7}):
            for n in os.listdir(self.dir):
                os.remove(os.path.join(self.dir, n))
            self.record(**kw)
            self.assertEqual(self.pending_work(), 1, kw)

    def test_any_active_record_of_the_conversation_wins_over_idle(self):
        self.record("shell")
        with open(os.path.join(self.dir, "%d.json" % os.getpid())) as f:
            d = json.load(f)
        with open(os.path.join(self.dir, "0-ikinci.json"), "w") as f:
            json.dump(dict(d, status="idle"), f)
        for order in (["0-ikinci.json", "%d.json" % os.getpid()], ["%d.json" % os.getpid(), "0-ikinci.json"]):
            with mock.patch.object(bg_work.os, "listdir", return_value=order):
                self.assertEqual(bg_work.session_record_status(self.dir, "s1"), "shell", order)

    def test_broken_record_and_missing_dir(self):
        with open(os.path.join(self.dir, "1.json"), "w") as f:
            f.write("[1")
        with open(os.path.join(self.dir, "2.json"), "w") as f:
            f.write("[]")
        self.assertIsNone(bg_work.session_record_status(self.dir, "s1"))
        self.assertIsNone(bg_work.session_record_status(os.path.join(self.dir, "yok"), "s1"))
        self.assertIsNone(bg_work.session_record_status(self.dir, None))

    def test_fifo_record_does_not_block(self):
        fifo = os.path.join(self.dir, "1.json")
        os.mkfifo(fifo)
        out = []
        t = threading.Thread(target=lambda: out.append(bg_work.session_record_status(self.dir, "s1")), daemon=True)
        t.start()
        t.join(5)
        if t.is_alive():                       # takılan okuyucuyu bırak: yazma ucu açılıp kapanınca EOF alır
            with open(fifo, "w"):
                pass
            t.join(5)
            self.fail("süreç kaydı okuması FIFO'da bloklandı")
        self.assertEqual(out, [None])
        self.record("busy")                    # sağlam kayıt FIFO'nun yanında yine okunur
        self.assertEqual(bg_work.session_record_status(self.dir, "s1"), "busy")

    def test_non_finite_pid_and_oversized_record_are_skipped(self):
        with open(os.path.join(self.dir, "1.json"), "w") as f:
            f.write('{"pid": Infinity, "sessionId": "s1", "status": "busy", "procStart": "1"}')
        self.assertIsNone(bg_work.session_record_status(self.dir, "s1"))
        self.record("busy")
        path = os.path.join(self.dir, f"{os.getpid()}.json")
        with open(path, "a") as f:
            f.write(" " * (1024 * 1024))
        self.assertIsNone(bg_work.session_record_status(self.dir, "s1"))


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
        with mock.patch("claudeops.providers.claude_provider.jsonl_path_for", return_value=Path(p)), \
             mock.patch.object(web_steward, "tmux_capture", return_value=""):
            self.assertTrue(web_steward.subagent_active_for("/x", "sid", name="n"))


if __name__ == "__main__":
    unittest.main()


class ProviderBackgroundWork(unittest.TestCase):
    def test_base_unknown_and_claude_counts(self):
        from claudeops.providers import PROVIDERS
        for n, p in PROVIDERS.items():
            if n not in ("claude", "codex", "ucli"):
                self.assertIsNone(p.background_work("1 shell · esc to interrupt", "/x", None), n)
        c = PROVIDERS["claude"]
        self.assertEqual(c.background_work(SCREEN_BG_TASKS, "/nonexistent", None), 2)      # "← 1 agent" sayılmaz
        self.assertEqual(c.background_work(SCREEN_SHELL, "/nonexistent", None), 1)
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


CODEX_SCREEN = """\
• Başladı.
  1 background terminal running · /ps to view · /stop to close
› Ask Codex to do anything
"""


def _sa(kind, aid, ts):
    return json.dumps({"timestamp": ts, "type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "SubAgentActivity", "kind": kind, "agent_thread_id": aid, "agent_path": "/root/x"}}})


class CodexBackgroundWork(unittest.TestCase):
    def test_screen_and_rollout(self):
        self.assertEqual(bg_work.codex_screen_count(CODEX_SCREEN), 1)
        self.assertEqual(bg_work.codex_screen_count("› Ask Codex to do anything\nWorked for 3s"), 0)
        ls = [_sa("started", "a1", "2026-11-23T10:17:26Z"), _sa("started", "a2", "2026-11-23T10:17:27Z"), _sa("completed", "a1", "2026-11-23T10:18:30Z")]
        self.assertEqual(bg_work.codex_subagents_pending(ls, now=T), 1)
        self.assertEqual(bg_work.codex_subagents_pending(ls, now=T + 7 * 3600), 0)

    def test_provider_sums_screen_and_missing_rollout(self):
        from claudeops.providers import PROVIDERS
        c = PROVIDERS["codex"]
        with mock.patch.object(type(c), "_rollout_path", return_value=None):
            self.assertEqual(c.background_work(CODEX_SCREEN, "/x", None), 1)
            self.assertEqual(c.background_work("› Ask Codex", "/x", None), 0)

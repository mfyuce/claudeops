"""21 Kas iso/copsdevderbent: pane'de izin diyaloğu ("Do you want to proceed?") varken cevap iletimi düz 'send failed' görünüyordu ve
loop_guard deliver_answer'ı 6 saat durduruyordu. Artık neden `dialog_blocked:<tür>` ve duraklatma 15 dk. Canlı servis/tmux YOK."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class SendFailResult(unittest.TestCase):
    def setUp(self):
        ws._SEND_FAILS.clear()
        ws._DIALOG_STUCK.clear()

    def test_dialog_reason_is_reported(self):
        ws._note_send_result("p", False, "dialog:unknown_dialog")
        ws._DIALOG_STUCK["p"] = {"kind": "unknown_dialog", "head": "│ working directories | Do you want to proceed?"}
        r = ws._send_fail_result("p")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "dialog_blocked:unknown_dialog")
        self.assertEqual(r["code"], "dialog_blocked")
        self.assertIn("Do you want to proceed", r["dialog"])

    def test_plain_failure_stays_send_failed(self):
        ws._note_send_result("q", False, "send failed")
        self.assertEqual(ws._send_fail_result("q"), {"ok": False, "error": "send failed"})
        self.assertEqual(ws._send_fail_result("never-seen"), {"ok": False, "error": "send failed"})


class LoopGuardDeliverAnswer(unittest.TestCase):
    def test_short_pause_then_retry(self):
        a = sw.Action("deliver_answer", "p", "answer", {"question_id": "q1"})
        st, now = {}, 1000.0
        out = []
        for i in range(sw.LOOP_MAX + 1):
            out, st = sw.loop_guard([a], [], st, now + i)
        self.assertEqual([x.kind for x in out], ["loop_break"])
        self.assertEqual(out[0].payload["pause_min"], 15)
        t_break = now + sw.LOOP_MAX
        mid, st = sw.loop_guard([a], [], st, t_break + 600)          # 10 dk: hâlâ duraklı
        self.assertEqual(mid, [])
        again, st = sw.loop_guard([a], [], st, t_break + 16 * 60)    # 16 dk: yeniden denenir
        self.assertEqual([x.kind for x in again], ["deliver_answer"])

    def test_other_kinds_keep_long_pause(self):
        a = sw.Action("nudge", "p", "x", {})
        st = {}
        for i in range(sw.LOOP_MAX + 1):
            out, st = sw.loop_guard([a], [], st, 1000.0 + i)
        self.assertEqual(out[0].payload["pause_h"], 6)


if __name__ == "__main__":
    unittest.main()


PERM = """ Bash command

   git -C /home/x/work/main status
   Check status

 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and don't ask again for git commands in /home/x/work
   3. No, and tell Claude what to do differently (esc)

 Esc to cancel
"""
READY = "╭────╮\n│ > │\n╰────╯\n  ? for shortcuts\n"


class PermissionDialog(unittest.TestCase):
    def test_classified_as_permission_not_pressed(self):
        from claudeops import trust_dialog as td
        cl = td.classify(PERM)
        self.assertEqual(cl[0], "permission")
        ws._DIALOG_STUCK.clear()
        with mock.patch.object(ws, "tmux_send_special_key") as key, mock.patch.object(ws, "tmux_send_raw") as raw, \
                mock.patch.object(ws, "_notify"), mock.patch.object(ws, "diag_log"), mock.patch.object(ws.sw, "log_event"):
            self.assertFalse(ws._recover_dialog("s", cl))
            key.assert_not_called()
            raw.assert_not_called()

    def test_brain_restart_refused_while_dialog_open_but_not_when_stale(self):
        ws._DIALOG_STUCK["s"] = {"kind": "permission", "head": "Do you want to proceed?"}
        with mock.patch.object(ws, "tmux_capture", return_value=PERM), mock.patch.object(ws.sw, "log_event"), \
                mock.patch.object(ws, "_gate", return_value=None), mock.patch.object(ws, "_upper_model_gate", return_value=None), \
                mock.patch.object(ws, "_brain_directive_blocks", return_value=None), mock.patch.object(ws, "_name_host", return_value=""), \
                mock.patch.object(ws, "steward_config", return_value=sw.Config()):
            r = ws.http_restart({"name": "s", "actor": "brain", "reason": "send failed"})
            self.assertFalse(r["ok"])
            self.assertEqual(r["code"], "dialog_blocked")
        # kayıt bayat (pane artık hazır): kapı açılır, kayıt silinir
        ws._DIALOG_STUCK["s"] = {"kind": "permission", "head": "x"}
        with mock.patch.object(ws, "tmux_capture", return_value=READY):
            self.assertFalse(ws._dialog_still_open("s"))
        self.assertNotIn("s", ws._DIALOG_STUCK)


class TrustRecheckRace(unittest.TestCase):
    TRUST = "Do you trust the files in this folder?\n ❯ 1. Yes, proceed\n   2. No, exit\n Enter to confirm · Esc to cancel\n"

    def test_stale_screen_after_accept_is_waited_out(self):
        from claudeops import trust_dialog as td
        # kabulden sonra ilk iki okuma hâlâ bayat diyalog, sonra hazır: gönderim DEVAM etmeli
        panes = iter([self.TRUST, self.TRUST, READY, READY, READY])
        ws._DIALOG_STUCK.clear()
        with mock.patch.object(ws, "_cwd_resolver", return_value=lambda n: os.getcwd()), \
                mock.patch.object(td, "handle", return_value="accepted"), \
                mock.patch.object(ws, "tmux_capture", side_effect=lambda *a, **k: next(panes, READY)), \
                mock.patch.object(ws.time, "sleep"), mock.patch.object(ws, "diag_log"), mock.patch.object(ws, "_wait_prompt_ready", return_value=True):
            self.assertTrue(ws._recover_dialog("x", ("trust", "Do you trust")))

    def test_dialog_that_never_clears_still_fails(self):
        from claudeops import trust_dialog as td
        ws._DIALOG_STUCK.clear()
        t = {"now": 0.0}
        with mock.patch.object(ws, "_cwd_resolver", return_value=lambda n: os.getcwd()), \
                mock.patch.object(td, "handle", return_value="accepted"), \
                mock.patch.object(ws, "tmux_capture", return_value=self.TRUST), \
                mock.patch.object(ws.time, "sleep", side_effect=lambda s: t.__setitem__("now", t["now"] + s)), \
                mock.patch.object(ws.time, "monotonic", side_effect=lambda: t["now"]), mock.patch.object(ws, "diag_log"):
            self.assertFalse(ws._recover_dialog("x", ("trust", "Do you trust")))

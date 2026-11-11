"""Diyalogda takılı oturum (11 Kas dalgicppr): tanı, kayıtlı klasörde güven diyaloğu geçişi, bilinmeyende kör tuş YOK + bildirim,
explain_idle dialog_stuck/send_failed."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw, trust_dialog as td  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402
from test_steward_ucli_idle import NOW, cview, proj  # noqa: E402

TRUST = "Welcome\n\n Do you trust the files in this folder?\n\n ❯ 1. Yes, proceed\n   2. No, exit\n\n Enter to confirm · Esc to cancel"
RESUME = "Select a conversation to resume\n\n ❯ 1. eski oturum\n   2. baska\n\n Enter to confirm"
UNKNOWN = "Bir seyi onayla\n\n ❯ 1. Evet\n   2. Hayir\n\n Enter to confirm · Esc to cancel"
READY = "● yaptim\n────\n❯ \n────\n  ⏵⏵ auto mode on (shift+tab to cycle)"


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(td.classify(TRUST)[0], "trust")
        self.assertEqual(td.classify(RESUME)[0], "resume_picker")
        self.assertEqual(td.classify(UNKNOWN)[0], "unknown_dialog")
        self.assertIsNone(td.classify(READY))
        self.assertIsNone(td.classify(""))

    def test_history_mention_is_not_dialog(self):
        self.assertIsNone(td.classify("trust this folder yazmistim\n" + READY))

    def test_head_is_first_two_lines(self):
        h = td.classify(UNKNOWN)[1]
        self.assertIn("Bir seyi onayla", h)
        self.assertLessEqual(h.count(" | "), 1)


class RecoverTest(unittest.TestCase):
    def setUp(self):
        ws._DIALOG_STUCK.clear()
        ws._SEND_FAILS.clear()

    def test_unknown_dialog_presses_no_keys_and_notifies_once(self):
        with mock.patch.object(ws, "tmux_send_special_key") as key, mock.patch.object(ws, "tmux_send_raw") as raw, \
                mock.patch.object(ws, "_notify") as nt, mock.patch.object(ws, "diag_log"), mock.patch.object(ws.sw, "log_event"):
            cl = td.classify(UNKNOWN)
            self.assertFalse(ws._recover_dialog("x", cl))
            self.assertFalse(ws._recover_dialog("x", cl))
            key.assert_not_called()
            raw.assert_not_called()
            self.assertEqual(nt.call_count, 1)
            self.assertIn("diyalogda takılı", nt.call_args[0][1])
        self.assertEqual(ws._DIALOG_STUCK["x"]["kind"], "unknown_dialog")

    def test_trust_unregistered_folder_not_touched(self):
        with mock.patch.object(ws, "_cwd_resolver", return_value=lambda n: ""), mock.patch.object(ws, "tmux_send_special_key") as key, \
                mock.patch.object(ws, "_notify"), mock.patch.object(ws, "diag_log"), mock.patch.object(ws.sw, "log_event"):
            self.assertFalse(ws._recover_dialog("x", td.classify(TRUST)))
            key.assert_not_called()

    def test_trust_registered_folder_accepted(self):
        panes = [TRUST, READY]
        def cap(name):
            return panes[0] if len(keys) == 0 else panes[1]
        keys = []
        with mock.patch.object(ws, "_cwd_resolver", return_value=lambda n: os.getcwd()), mock.patch.object(ws, "tmux_capture", side_effect=cap), \
                mock.patch.object(ws, "tmux_send_special_key", side_effect=lambda n, k: keys.append(k) or True), \
                mock.patch.object(ws, "tmux_send_raw", return_value=True), mock.patch.object(ws, "_notify") as nt, mock.patch.object(ws, "diag_log"):
            self.assertTrue(ws._recover_dialog("x", td.classify(TRUST)))
        self.assertEqual(keys, ["Enter"])
        nt.assert_not_called()
        self.assertNotIn("x", ws._DIALOG_STUCK)

    def test_send_fail_streak_notifies(self):
        with mock.patch.object(ws, "_notify") as nt, mock.patch.object(ws.sw, "log_event"):
            for _ in range(3):
                ws._note_send_result("y", False, "send failed")
            self.assertEqual(nt.call_count, 1)
            ws._note_send_result("y", True)
            self.assertNotIn("y", ws._SEND_FAILS)


class ExplainTest(unittest.TestCase):
    def test_dialog_stuck_and_send_failed_codes(self):
        c = sw.Config(enabled=True, mode="act", claude_idle="act")
        v = cview(last_assistant="")
        st = {"dialog_stuck": {"cli": {"kind": "trust", "head": "Do you trust", "since": NOW}}}
        self.assertEqual(sw.explain_idle_all([v], proj(""), st, c, NOW, [])["cli"]["code"], "dialog_stuck")
        st = {"send_fail": {"cli": {"n": 4, "error": "send failed", "since": NOW}}}
        self.assertEqual(sw.explain_idle_all([v], proj(""), st, c, NOW, [])["cli"]["code"], "send_failed")
        st = {"send_fail": {"cli": {"n": 2, "error": "x", "since": NOW}}}
        self.assertNotEqual(sw.explain_idle_all([v], proj(""), st, c, NOW, [])["cli"]["code"], "send_failed")


if __name__ == "__main__":
    unittest.main()

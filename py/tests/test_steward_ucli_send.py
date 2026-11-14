"""ucli'ye giden metin tek satıra katlanır (kesmeden) + gönderim sonrası kutu kontrolü. Gerçek tmux YOK (sahte)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_steward as ws  # noqa: E402
from claudeops.providers import get_provider  # noqa: E402


class _Prov:
    """Gerçek katlama kuralı: ucli için UcliProvider.prepare_input, diğerleri dokunmaz."""
    def __init__(self, cli="claude"): self.cli = cli
    def has_conversation(self): return True
    def prepare_input(self, t):
        return get_provider("ucli").prepare_input(t) if self.cli == "ucli" else t
    def input_settle_delay(self): return 0.0


class UcliSendTest(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(ws, "get_provider", lambda cli: _Prov(cli)),
                  mock.patch.object(ws, "UCLI_BOX_CHECK_DELAY", 0.0),
                  mock.patch.object(ws.sw, "log_event")):
            p.start()
            self.addCleanup(p.stop)
        self.log = ws.sw.log_event

    def test_ucli_text_folded_not_truncated(self):
        long = "satır1\n" + ("uzun " * 400) + "\nson"
        with mock.patch.object(ws, "tmux_send_keys", return_value=True) as sk, \
                mock.patch.object(ws, "tmux_capture", return_value="ucli> \n"):
            self.assertTrue(ws._send("u", "ucli", long))
        sent = sk.call_args[0][1]
        self.assertNotIn("\n", sent)
        self.assertTrue(sent.endswith("son"))
        self.assertGreater(len(sent), 400)

    def test_non_ucli_untouched_and_no_recheck(self):
        with mock.patch.object(ws, "tmux_send_keys", return_value=True) as sk, \
                mock.patch.object(ws, "tmux_capture", return_value="> \n") as cap:
            ws._send("c", "claude", "a\nb")
        self.assertEqual(sk.call_args[0][1], "a\nb")
        self.assertEqual(cap.call_count, 1)             # yalniz guven diyalogu korumasi, ucli kutu denetimi YOK

    def test_claude_trust_dialog_blocks_send(self):
        dlg = "Do you trust the files in this folder?\n 1. Yes, proceed\n 2. No, exit\n"
        with mock.patch.object(ws, "tmux_send_keys", return_value=True) as sk, \
                mock.patch.object(ws, "tmux_capture", return_value=dlg), \
                mock.patch.object(ws, "diag_log"):
            self.assertFalse(ws._send("c", "claude", "devam"))
        sk.assert_not_called()

    def test_text_left_in_box_sends_one_more_enter(self):
        import itertools
        caps = itertools.chain(["ucli> kalan metin\n"], itertools.repeat("ucli> \n"))
        with mock.patch.object(ws, "tmux_send_keys", return_value=True), \
                mock.patch.object(ws, "tmux_capture", side_effect=lambda *a, **k: next(caps)), \
                mock.patch.object(ws, "tmux_send_raw") as raw:
            ws._send("u", "ucli", "x")
        raw.assert_called_once_with("u", "\r")
        self.log.assert_not_called()

    def test_still_stuck_logs_error(self):
        with mock.patch.object(ws, "tmux_send_keys", return_value=True), \
                mock.patch.object(ws, "tmux_capture", return_value="ucli> kalan\n"), \
                mock.patch.object(ws, "tmux_send_raw") as raw:
            ws._send("u", "ucli", "x")
        self.assertEqual(raw.call_count, ws.UCLI_BOX_MAX_ENTERS)      # sınırlı sayıda Enter, sonra olay
        self.assertEqual(self.log.call_args[0][0], "ucli_send_stuck")

    def test_stuck_event_uses_caller_sid(self):
        with mock.patch.object(ws, "tmux_send_keys", return_value=True), \
                mock.patch.object(ws, "tmux_capture", return_value="ucli> kalan\n"), \
                mock.patch.object(ws, "tmux_send_raw"), \
                mock.patch.object(ws.sw, "paths_for") as pf:
            ws._send("u", "ucli", "x", sid="proj1")
        pf.assert_called_with("proj1")

    def test_late_drawn_text_gets_enter(self):
        """Metin ilk yoklamalarda henüz çizilmemiş (boş kutu), sonra belirir: Enter yine gider."""
        import itertools
        caps = itertools.chain(["ucli> \n", "ucli> \n", "ucli> geç gelen\n"], itertools.repeat("ucli> \n"))
        with mock.patch.object(ws, "tmux_send_keys", return_value=True), \
                mock.patch.object(ws, "tmux_capture", side_effect=lambda *a, **k: next(caps)), \
                mock.patch.object(ws, "tmux_send_raw") as raw:
            ws._send("u", "ucli", "x")
        raw.assert_called_once_with("u", "\r")
        self.log.assert_not_called()

    def test_empty_box_no_extra_enter(self):
        with mock.patch.object(ws, "tmux_send_keys", return_value=True), \
                mock.patch.object(ws, "tmux_capture", return_value="cevap\nucli> \n"), \
                mock.patch.object(ws, "tmux_send_raw") as raw:
            ws._send("u", "ucli", "x")
        raw.assert_not_called()


class BoxTextTest(unittest.TestCase):
    P = "[claude-sonnet-5-5 | turn 8 | 180.8 KiB] ucli>"

    def box(self, pane):
        with mock.patch.object(ws, "tmux_capture", return_value=pane):
            return ws._ucli_box_text("u")

    def test_prefixed_empty_prompt(self):
        self.assertEqual(self.box("cevap\n" + self.P + " \n"), "")

    def test_prefixed_with_text(self):
        self.assertEqual(self.box("cevap\n" + self.P + " devam: testleri yaz\n"), "devam: testleri yaz")

    def test_text_wrapped_over_two_lines(self):
        pane = "eski\n" + self.P + " devam: " + "a" * 60 + "\n" + "b" * 20 + "\n"
        self.assertEqual(self.box(pane), "devam: " + "a" * 60 + " " + "b" * 20)

    def test_waiting_for_response_is_empty(self):
        self.assertEqual(self.box(self.P + " devam: x\nwaiting for response...\n"), "")

    def test_turn_output_after_prompt_is_empty(self):
        self.assertEqual(self.box(self.P + " devam: x\n● cevap geldi\n"), "")

    def test_last_prompt_line_wins(self):
        self.assertEqual(self.box(self.P + " eski\ncevap\n" + self.P + " \n"), "")

    def test_no_prompt(self):
        self.assertEqual(self.box("yalnız çıktı\n"), "")


if __name__ == "__main__":
    unittest.main()

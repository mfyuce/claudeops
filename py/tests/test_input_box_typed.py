"""Claude TUI giriş kutusunda gönderilmemiş metin tespiti (keepwarm bunun doluyken gitmez; stdlib unittest, tmux YOK)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import tmux_backend as tb  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

RULE = "\x1b[38;5;244m" + "─" * 20 + "\x1b[39m"
PROMPT_GREY = "\x1b[38;5;246m❯ \x1b[39m"


def screen(box_line):
    return "\x1b[38;5;246m  tip\x1b[39m\n\n" + RULE + "\n" + box_line + "\n" + RULE + "\n  auto mode on\n"


class TypedBoxTest(unittest.TestCase):
    def test_empty_box_is_not_typed(self):          # gerçek boş kutu: gri istem + NBSP
        self.assertIs(tb.typed_input_in_box(screen(PROMPT_GREY)), False)

    def test_grey_suggestion_is_not_typed(self):    # TUI'nin gri "devam" önerisi yazılmış metin DEĞİL
        self.assertIs(tb.typed_input_in_box(screen(PROMPT_GREY + "\x1b[38;5;246mdevam\x1b[39m")), False)
        self.assertIs(tb.typed_input_in_box(screen("❯ \x1b[2mdevam\x1b[22m")), False)

    def test_default_color_text_is_typed(self):
        self.assertIs(tb.typed_input_in_box(screen(PROMPT_GREY + "merhaba")), True)
        self.assertIs(tb.typed_input_in_box(screen("❯ hello world")), True)
        self.assertIs(tb.typed_input_in_box(screen(PROMPT_GREY + "\x1b[39mmerhaba\x1b[0m")), True)

    def test_whitespace_only_and_borders_ignored(self):
        self.assertIs(tb.typed_input_in_box(screen("❯     ")), False)

    def test_no_box_is_unknown(self):
        self.assertIsNone(tb.typed_input_in_box("sadece log satırları\nbaşka\n"))
        self.assertIsNone(tb.typed_input_in_box(""))
        self.assertIsNone(tb.typed_input_in_box(None))

    def test_last_box_wins(self):
        old = screen("❯ eski yazı")
        self.assertIs(tb.typed_input_in_box(old + screen(PROMPT_GREY)), False)

    def test_helper_false_on_error_and_unknown(self):
        with mock.patch.object(tb, "tmux_pane_snapshot", side_effect=OSError("x")):
            self.assertFalse(ws._box_has_typed_input("s"))
        with mock.patch.object(tb, "tmux_pane_snapshot", return_value=(("1",), "log\n")):
            self.assertFalse(ws._box_has_typed_input("s"))
        with mock.patch.object(tb, "tmux_pane_snapshot", return_value=(("1",), screen("❯ yazılı"))):
            self.assertTrue(ws._box_has_typed_input("s"))


class KeepwarmApplyTest(unittest.TestCase):
    def _apply(self, typed):
        from claudeops import steward as sw
        sess = mock.Mock(pid=1, cli="claude")
        sess.name = "cli"
        cfg = sw.Config(enabled=True)
        proj = {"cli": sw.Project(name="cli", phase="planned")}
        with mock.patch.object(ws, "_running", return_value=sess), mock.patch.object(ws, "is_tmux_backed", return_value=True), \
                mock.patch.object(ws, "_target", return_value=None), mock.patch.object(ws, "_box_has_typed_input", return_value=typed), \
                mock.patch.object(ws, "_send", return_value=True) as send, mock.patch.object(ws.sw, "log_event") as log:
            res = ws._apply(sw.Action("keepwarm", "cli", "x", {}), cfg, proj)
        return res, send, log

    def test_box_full_skips_keepwarm(self):
        res, send, log = self._apply(True)
        self.assertFalse(res["ok"])
        send.assert_not_called()                                       # kutudaki direktife "ok" eklenmez
        self.assertEqual(log.call_args.args[0], "keepwarm_skipped")

    def test_box_empty_sends_keepwarm(self):
        res, send, _log = self._apply(False)
        self.assertTrue(res["ok"])
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()

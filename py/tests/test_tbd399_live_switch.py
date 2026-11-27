"""TBD#399 (sahip onayı, 27 Kas): devir sırasında claude oturumunda canlı model/effort geçişi. Kural: EMİN OLUNAMAYAN
EKRANDA TUŞ GÖNDERİLMEZ ve sonuç çağırana görünür döner. Gerçek tmux/claude YOK (sahte pane + sahte saat).

Ekranlar: giriş kutusu `test_directive_delivery.box` (Claude Code 2.1.332 yakalaması), izin sorusu
`test_steward_answer_dialog_blocked.PERM`, geçiş diyaloğu 2.1.332 ikilisindeki bileşenin metinleri (başlık,
"Yes, switch to X", "No, go back"; imleç/numara düzeni izin ve güven diyaloğu örnekleriyle aynı).

Çalıştırma:  python3 -m unittest tests.test_tbd399_live_switch  (py/ içinden)
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudeops import handover, paths  # noqa: E402
from claudeops import tmux_backend as tb  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402
from claudeops.providers.claude_provider import ClaudeProvider  # noqa: E402
from tui_screens import (BUSY, DIALOG, DRAFT, EFFORT, IDLE, PERMISSION, SUGGESTION, box, dialog,  # noqa: E402
                         result)

SAFE = ("done", "busy")


class Pane:
    """`send` komutu yazılınca `after`, Enter/Down sonrası `on_key` ekranları gösterir."""

    def __init__(self, before, after=(), on_key=None, send_ok=True, key_ok=None):
        self.screens, self.after, self.on_key = [before], list(after), on_key or {}
        self.send_ok, self.key_ok = send_ok, key_ok or {}
        self.texts, self.keys, self.now = [], [], 0.0

    def capture(self, name, lines=2000):
        if len(self.screens) > 1:
            return self.screens.pop(0)
        return self.screens[0]

    def send(self, name, text, *a, **k):
        self.texts.append(text)
        if self.send_ok and self.after:
            self.screens = list(self.after)
        return self.send_ok

    def key(self, name, key):
        self.keys.append(key)
        ok = self.key_ok.get(key, True)
        if ok and self.on_key.get(key):
            self.screens = list(self.on_key[key].pop(0))
        return ok

    def sleep(self, s):
        self.now += s

    def run(self, fn):
        with mock.patch.object(tb, "tmux_capture", self.capture), mock.patch.object(tb, "tmux_send_keys", self.send), \
                mock.patch.object(tb, "tmux_send_special_key", self.key), \
                mock.patch.object(cp.time, "monotonic", lambda: self.now), mock.patch.object(cp.time, "sleep", self.sleep), \
                mock.patch.object(cp, "diag_log", lambda *a, **k: None):
            return fn()


def model(p):
    return p.run(lambda: ClaudeProvider().apply_live_model_switch("s", "sonnet"))


def effort(p):
    return p.run(lambda: ClaudeProvider().apply_live_effort_switch("s", "high"))


def dismiss(p):
    return p.run(lambda: ClaudeProvider().dismiss_stray_dialog("s"))


def val(out):
    return getattr(out, "value", out)


class StaleResultText(unittest.TestCase):
    """(1)"""

    def test_old_marker_does_not_end_the_wait_and_the_late_dialog_is_confirmed(self):
        old = box(history=result("Set model to Sonnet 5.5"))
        new = box(history=result("Set model to Sonnet 5.5") + "\n" + result("Set model to Sonnet 5.5"))
        p = Pane(old, after=[old, old, DIALOG], on_key={"Enter": [[new]]})
        self.assertEqual(val(model(p)), "done")
        self.assertEqual(p.keys, ["Enter"])

    def test_old_effort_marker_alone_is_unconfirmed(self):
        old = box(history=result("Set effort level to high"))
        p = Pane(old)
        self.assertEqual(val(effort(p)), "unconfirmed")
        self.assertEqual(p.keys, [])

    def test_new_marker_is_done(self):
        p = Pane(IDLE, after=[box(history=result("Set effort level to high"))])
        self.assertEqual(val(effort(p)), "done")
        self.assertEqual(p.keys, [])

    def test_claude_refusal_is_a_finished_command(self):
        p = Pane(IDLE, after=[box(history=result("Not applied: x"))])
        self.assertEqual(val(effort(p)), "done")


class OnlyTheOpenExpectedDialog(unittest.TestCase):
    """(2)"""

    def test_dialog_text_in_conversation_does_not_confirm_a_permission_prompt(self):
        screen = result("Switch model?") + "\n" + result("Change effort level?") + "\n" + PERMISSION
        for fn in (model, effort):
            p = Pane(IDLE, after=[screen])
            self.assertEqual(val(fn(p)), "unconfirmed")
            self.assertEqual(p.keys, [])

    def test_stray_scan_never_touches_a_permission_prompt(self):
        p = Pane(result("Switch model?") + "\n" + PERMISSION)
        self.assertIsNone(dismiss(p))
        self.assertEqual(p.keys, [])

    def test_quoted_dialog_above_the_input_box_is_not_open(self):
        p = Pane(box(history=DIALOG))
        self.assertIsNone(dismiss(p))
        self.assertEqual(p.keys, [])

    def test_wrong_kind_wrong_label_or_cursor_on_no_is_not_confirmed(self):
        for screen in (EFFORT, dialog("Switch model?", "Opus 5.5"), dialog("Switch model?", "Sonnet 5.5", on_no=True),
                       DIALOG + "\n  3. Something else", dialog("Switch models?", "Sonnet 5.5")):
            p = Pane(IDLE, after=[screen])
            self.assertEqual(val(model(p)), "unconfirmed", screen)
            self.assertEqual(p.keys, [], screen)

    def test_precondition_refuses_when_any_dialog_is_open_or_screen_unknown(self):
        for screen, want in ((PERMISSION, "unreadable"), (DIALOG, "dialog"), (None, "unreadable"), ("", "unreadable"),
                             (IDLE + "\n" + PERMISSION, "unreadable")):
            p = Pane(screen)
            self.assertEqual(val(model(p)), want, screen)
            self.assertEqual((p.texts, p.keys), ([], []))


class Draft(unittest.TestCase):
    """(3)"""

    def test_typed_draft_blocks_both_commands(self):
        for fn in (model, effort):
            p = Pane(DRAFT)
            self.assertEqual(val(fn(p)), "draft")
            self.assertEqual((p.texts, p.keys), ([], []))

    def test_dim_suggestion_is_not_a_draft(self):
        p = Pane(SUGGESTION, after=[box(history=result("Set model to Sonnet 5.5"))])
        self.assertEqual(val(model(p)), "done")
        self.assertEqual(p.texts, ["/model sonnet"])

    def test_busy_session_gets_no_command_and_is_safe_to_message(self):
        p = Pane(BUSY)
        self.assertEqual(val(effort(p)), "busy")
        self.assertEqual((p.texts, p.keys), ([], []))


class LateDialog(unittest.TestCase):
    """(4)"""

    def test_late_effort_dialog_is_refused(self):
        p = Pane(EFFORT, on_key={"Down": [[dialog("Change effort level?", "high", on_no=True)]], "Enter": [[IDLE]]})
        self.assertEqual(val(dismiss(p)), "done")
        self.assertEqual(p.keys, ["Down", "Enter"])

    def test_late_model_dialog_is_refused(self):
        p = Pane(DIALOG, on_key={"Down": [[dialog("Switch model?", "Sonnet 5.5", on_no=True)]], "Enter": [[IDLE]]})
        self.assertEqual(val(dismiss(p)), "done")
        self.assertEqual(p.keys, ["Down", "Enter"])


class KeyResultsAreChecked(unittest.TestCase):
    """(5)"""

    def test_failed_confirm_enter_is_reported(self):
        p = Pane(IDLE, after=[DIALOG], key_ok={"Enter": False})
        self.assertEqual(val(model(p)), "unconfirmed")
        self.assertEqual(p.keys, ["Enter"])
        self.assertLess(p.now, 1.0)

    def test_ignored_confirm_enter_is_not_repeated(self):
        p = Pane(IDLE, after=[DIALOG])
        self.assertEqual(val(model(p)), "unconfirmed")
        self.assertEqual(p.keys, ["Enter"])

    def test_failed_command_send_is_reported(self):
        p = Pane(IDLE, send_ok=False)
        self.assertEqual(val(model(p)), "send_failed")
        self.assertEqual(p.keys, [])

    def test_down_that_did_not_move_the_cursor_gets_no_enter(self):
        for after_down in (DIALOG, PERMISSION, None, EFFORT.replace("❯ 1.", "  1.").replace("  2.", "❯ 2.")):
            p = Pane(DIALOG, on_key={"Down": [[after_down]]})
            self.assertEqual(val(dismiss(p)), "unconfirmed", after_down)
            self.assertEqual(p.keys, ["Down"], after_down)

    def test_dialog_still_open_after_refusing_is_reported(self):
        no = dialog("Switch model?", "Sonnet 5.5", on_no=True)
        p = Pane(no)
        self.assertEqual(val(dismiss(p)), "unconfirmed")
        self.assertEqual(p.keys, ["Enter"])

    def test_dialog_in_the_last_look_is_confirmed_and_verified(self):
        applied = box(history=result("Set model to Sonnet 5.5"))
        p = Pane(IDLE, after=[DIALOG], on_key={"Enter": [[applied]]})
        with mock.patch.object(ClaudeProvider, "_MODEL_SWITCH_TIMEOUT_SECONDS", 0.0):
            self.assertEqual(val(model(p)), "done")
        self.assertEqual(p.keys, ["Enter"])


class CallersDoNotType(unittest.TestCase):
    """Devir akışı: geçiş güvenli bitmediyse mesaj gönderilmez, sonuç görünür."""

    def _provider(self, model_out=None, effort_out=None):
        calls = []

        class P(ClaudeProvider):
            def apply_live_model_switch(self, n, t):
                calls.append("model")
                return cp._Switch(model_out) if model_out else None

            def apply_live_effort_switch(self, n, t):
                calls.append("effort")
                if effort_out == "raise":
                    raise RuntimeError("x")
                return cp._Switch(effort_out) if effort_out else None

            def dismiss_stray_dialog(self, n):
                calls.append("dismiss")

            def prompt_cache_ttl_seconds(self):
                return None
        return P(), calls

    def _apply(self, prov):
        with mock.patch.object(handover, "live_or_spawn_model", return_value="claude-opus-5-5"), \
                mock.patch.object(handover, "live_or_spawn_effort", return_value="max"), \
                mock.patch.object(handover, "default_handover_effort", return_value="high"), \
                mock.patch.object(handover, "diag_log", lambda *a, **k: None):
            return handover.apply_handover_downgrades(prov, "s", "claude", "/w", "sid", None, None)

    def test_blocked_model_step_stops_before_effort(self):
        for out in ("draft", "dialog", "unreadable", "send_failed", "unconfirmed"):
            prov, calls = self._provider(model_out=out)
            res = self._apply(prov)
            self.assertEqual((res.blocked, calls), (f"model:{out}", ["model"]))

    def test_blocked_effort_step(self):
        for out, want in (("unconfirmed", "effort:unconfirmed"), ("raise", "effort:error")):
            prov, calls = self._provider(model_out="done", effort_out=out)
            res = self._apply(prov)
            self.assertEqual((res.blocked, res.effort_to), (want, None))

    def test_done_and_busy_do_not_block(self):
        for out in SAFE:
            prov, _ = self._provider(model_out=out, effort_out=out)
            res = self._apply(prov)
            self.assertEqual(res.blocked, "")
            self.assertEqual((res.model_to, res.effort_to), ("sonnet", "high") if out == "done" else (None, None))

    def test_web_handover_sends_nothing_and_says_why(self):
        prov, calls = self._provider(model_out="unconfirmed")
        proc = mock.Mock(pid=1, cli="claude", cwd="/w", sid="sid", model=None, effort=None)
        proc.name = "s"
        with mock.patch.object(web, "_find_running_for_action", return_value=("exact", [proc])), \
                mock.patch.object(web, "is_tmux_backed", return_value=True), \
                mock.patch.object(web, "get_provider", return_value=prov), \
                mock.patch.object(web, "diag_log", lambda *a, **k: None), \
                mock.patch.object(web, "apply_handover_downgrades",
                                  return_value=handover.HandoverDowngrade(blocked="model:unconfirmed")), \
                mock.patch.object(web, "tmux_send_keys") as send:
            res = web._handover("s")
        send.assert_not_called()
        self.assertEqual((res["ok"], res["code"]), (False, "handover_switch_blocked"))
        self.assertIn("model:unconfirmed", res["error"])
        self.assertEqual(calls, ["dismiss"])

    def test_batch_handover_sends_nothing_and_counts_a_failure(self):
        prov, calls = self._provider(model_out="draft")
        sess = mock.Mock(pid=1, cli="claude", cwd="/w", sid="sid", model=None, effort=None, base="s", pid_str="1")
        sess.name = "s"
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(paths, "STATE_DIR", Path(tmp)), \
                mock.patch.object(handover, "find_sessions", return_value=[sess]), \
                mock.patch.object(handover, "ancestor_pids", return_value=set()), \
                mock.patch.object(handover, "get_provider", return_value=prov), \
                mock.patch.object(handover, "is_tmux_backed", return_value=True), \
                mock.patch.object(handover, "apply_handover_downgrades",
                                  return_value=handover.HandoverDowngrade(blocked="model:draft")), \
                mock.patch.object(handover, "diag_log", lambda *a, **k: None), \
                mock.patch.object(handover, "tmux_send_keys") as send, \
                contextlib.redirect_stdout(io.StringIO()):
            summary = handover.handover_faz1(names=["s"], batch_delay=0)
        send.assert_not_called()
        self.assertEqual([(r.status, r.detail) for r in summary.results], [("failed-switch", "model:draft")])
        self.assertEqual((summary.failed, calls), (1, ["dismiss"]))


if __name__ == "__main__":
    unittest.main()

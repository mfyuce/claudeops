"""PROC-08: `apply_live_model_switch` son Enter'i YALNIZ "Switch model?" ekrandaysa gonderir (izin diyalogunu onaylamaz)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import tmux_backend as tb  # noqa: E402
from claudeops.providers.claude_provider import ClaudeProvider  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tui_screens import DIALOG, IDLE, PERMISSION, box, result  # noqa: E402

APPLIED = box(history=result("Set model to Sonnet 5.5"))


class NoBlindEnterTest(unittest.TestCase):
    def _run(self, screens):
        keys = []
        last = {"v": screens[-1]}

        def cap(name, lines=20):
            try:
                last["v"] = next(it)
            except StopIteration:
                pass
            return last["v"]
        p = ClaudeProvider()
        it = iter([IDLE] + screens)       # ilk yakalama komuttan ÖNCEKİ ekran (TBD#399)
        with mock.patch.object(tb, "tmux_send_keys", lambda n, t: True), \
                mock.patch.object(tb, "tmux_capture", cap), \
                mock.patch.object(tb, "tmux_send_special_key", lambda n, k: keys.append(k)), \
                mock.patch.object(type(p), "_MODEL_SWITCH_TIMEOUT_SECONDS", 0.05), \
                mock.patch.object(type(p), "_MODEL_SWITCH_POLL_SECONDS", 0.01):
            p.apply_live_model_switch("s", "sonnet")
        return keys

    def test_permission_dialog_is_not_confirmed(self):
        self.assertEqual(self._run([PERMISSION]), [])

    def test_switch_dialog_confirmed_once(self):
        self.assertEqual(self._run([DIALOG, APPLIED]), ["Enter"])

    def test_applied_without_dialog(self):
        self.assertEqual(self._run([APPLIED]), [])


if __name__ == "__main__":
    unittest.main()

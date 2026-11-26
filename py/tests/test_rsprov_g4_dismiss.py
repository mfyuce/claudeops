"""rs/prov G4: `dismiss_stray_dialog` "Down" gönderilemezse Enter basmaz.

Diyaloğun seçili düğmesi 1. seçenektir ("Yes, switch"); `Down` ulaşmadan gönderilen Enter, reddedilmek istenen model
değişikliğini ONAYLAR. Gerçek tmux YOK (sahte).

Çalıştırma:  python3 -m unittest tests.test_rsprov_g4_dismiss  (py/ içinden)
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import tmux_backend as tb  # noqa: E402
from claudeops.providers.claude_provider import ClaudeProvider  # noqa: E402


class DismissStrayDialogTest(unittest.TestCase):
    def _run(self, results):
        keys = []

        def send(name, key):
            keys.append(key)
            return results.get(key, True)
        with mock.patch.object(tb, "tmux_capture", lambda *a, **k: "Switch model?\n 1. Yes\n 2. No, go back"), \
                mock.patch.object(tb, "tmux_send_special_key", send), \
                mock.patch.object(ClaudeProvider, "_STRAY_DIALOG_TIMEOUT_SECONDS", 0.05), \
                mock.patch.object(ClaudeProvider, "_STRAY_DIALOG_POLL_SECONDS", 0.01):
            ClaudeProvider().dismiss_stray_dialog("s")
        return keys

    def test_failed_down_sends_no_enter(self):
        self.assertEqual(self._run({"Down": False}), ["Down"])

    def test_successful_down_is_followed_by_enter(self):
        self.assertEqual(self._run({}), ["Down", "Enter"])


if __name__ == "__main__":
    unittest.main()

"""859: ucli last_exchange eski assistant cevabını yeni user turuyla eşleştirmez (full_history sahte; disk YOK)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import ucli_provider as up  # noqa: E402


class LastExchangePairingTest(unittest.TestCase):
    def _ex(self, turns):
        p = up.UcliProvider()
        with mock.patch.object(up.UcliProvider, "full_history", lambda self, cwd, sid: turns):
            return p.last_exchange("/x", "s")

    def test_pending_user_turn_has_empty_assistant(self):
        r = self._ex([{"role": "user", "text": "a"}, {"role": "assistant", "text": "OLD COPS-END"},
                      {"role": "user", "text": "b"}])
        self.assertEqual(r, {"user": "b", "assistant": ""})

    def test_answered_turn_pairs_normally(self):
        r = self._ex([{"role": "user", "text": "a"}, {"role": "assistant", "text": "A"}])
        self.assertEqual(r, {"user": "a", "assistant": "A"})

    def test_assistant_only_and_empty(self):
        self.assertEqual(self._ex([{"role": "assistant", "text": "A"}]), {"user": "", "assistant": "A"})
        # [] = henüz mesaj yok -> boş sözlük (claude ile aynı), None = okunamaz/sid yok
        self.assertEqual(self._ex([]), {"user": "", "assistant": ""})
        self.assertIsNone(self._ex(None))


if __name__ == "__main__":
    unittest.main()

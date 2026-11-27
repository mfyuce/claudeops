"""TBD#399 (6): pane'e giden metindeki denetim karakterleri aynen geçmez; yalnız satır sonu/boşluk/denetim karakterinden
oluşan metin tek başına Enter'a dönüşmez. Gerçek tmux YOK (`subprocess.run` sahte).

Çalıştırma:  python3 -m unittest discover -s tests -p test_tbd399_control_chars.py  (py/ içinden)
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import tmux_backend as tb  # noqa: E402
from claudeops.providers.ucli_provider import UcliProvider  # noqa: E402


class SendText(unittest.TestCase):
    def _send(self, text):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw.get("input")))
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        with mock.patch.object(tb.subprocess, "run", run), mock.patch.object(tb.time, "sleep", lambda s: None):
            ok = tb.tmux_send_keys("s", text, guard=False)
        return ok, calls

    def test_control_characters_are_removed_but_newline_tab_cr_stay(self):
        ok, calls = self._send("a\x03b\x1b[201~c\x7fd\x9be\nf\tg\rh ş")
        self.assertTrue(ok)
        self.assertEqual(calls[0][1].decode(), "ab[201~cde\nf\tg\rh ş")

    def test_every_other_control_character_is_removed(self):
        bad = "".join(chr(c) for c in list(range(1, 32)) + list(range(127, 160)) if chr(c) not in "\t\n\r")
        ok, calls = self._send("x" + bad + "y")
        self.assertTrue(ok)
        self.assertEqual(calls[0][1], b"xy")

    def test_text_with_nothing_but_blanks_and_controls_sends_nothing(self):
        for text in ("\n", "\r\n\r\n", " \t\n", "\x03", "\x1b\n", "\x04\x15"):
            self.assertEqual(self._send(text), (False, []), repr(text))

    def test_empty_text_is_still_a_deliberate_enter(self):
        ok, calls = self._send("")
        self.assertTrue(ok)
        self.assertEqual([c[0][-1] for c in calls], ["Enter"])

    def test_ucli_folding_never_turns_newlines_into_an_empty_enter(self):
        for text in ("\n", "\r\n \t\n"):
            self.assertEqual(UcliProvider().prepare_input(text), text)
            self.assertEqual(self._send(UcliProvider().prepare_input(text)), (False, []))
        self.assertEqual(UcliProvider().prepare_input("a\n\nb\n"), "a b")


if __name__ == "__main__":
    unittest.main()

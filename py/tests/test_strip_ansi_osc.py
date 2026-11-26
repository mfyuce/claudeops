"""OSC dizisi BEL ile de ST (`ESC \\`) ile de biter; ikisi de silinir."""
import unittest

from claudeops.tmux_backend import strip_ansi


class OscTerminatorTests(unittest.TestCase):
    def test_both_terminators_are_removed(self):
        cases = {
            "a\x1b]0;baslik\x07b": "ab",
            "a\x1b]0;baslik\x1b\\b": "ab",
            "\x1b]8;;http://x\x1b\\bag\x1b]8;;\x1b\\ son": "bag son",
            "\x1b]0;x\x1b\\gorunur\x1b]0;y\x07": "gorunur",
            "a\x1b]yarim": "a\x1b]yarim",
        }
        for raw, want in cases.items():
            self.assertEqual(strip_ansi(raw), want, repr(raw))


if __name__ == "__main__":
    unittest.main()

"""Ortak güvenli env-adı doğrulaması: 4 modülde kopyaydı; `$` + match sondaki satır sonunu kabul ediyordu (review cops R-7)."""
import unittest

from claudeops.envnames import is_safe_env_name
from claudeops import spawn


class EnvNames(unittest.TestCase):
    def test_valid_and_invalid(self):
        for ok in ("FOO", "_X1", "OPENAI_API_KEY"):
            self.assertTrue(is_safe_env_name(ok), ok)
        for bad in ("foo", "1A", "A-B", "A B", "A;rm", "FOO\n", "", None, 5):
            self.assertFalse(is_safe_env_name(bad), repr(bad))

    def test_spawn_filters_newline_and_dangerous(self):
        out = spawn._filter_env_overrides({"GOOD": "1", "BAD\n": "x", "LD_PRELOAD": "y", "a b": "z"})
        self.assertEqual(out, {"GOOD": "1"})


if __name__ == "__main__":
    unittest.main()

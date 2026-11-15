"""spawn._filter_env_overrides: geçersiz ad ve süreç/kabuğu ele geçirebilen değişkenler komut satırına gömülmez."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import spawn  # noqa: E402


class EnvFilter(unittest.TestCase):
    def test_filters(self):
        out = spawn._filter_env_overrides({"COPS_NAME": "x", "CODEX_HOME": "/h", "LD_PRELOAD": "/e.so", "BASH_ENV": "/e",
                                           "FOO; rm -rf /": "1", "lower": "1", "PATH": "/bin"})
        self.assertEqual(set(out), {"COPS_NAME", "CODEX_HOME", "PATH"})


if __name__ == "__main__":
    unittest.main()

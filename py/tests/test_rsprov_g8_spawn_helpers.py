"""rs/prov G8: spawn yardımcıları (yardım yoklaması, araç zinciri, PATH listesi). Yalnız geçici dizin ve sahte betik."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_client, ucli_session_opts as uso  # noqa: E402


def _script(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)


class HelpProbe(unittest.TestCase):
    def test_chat_help_does_not_read_the_callers_stdin(self):
        with tempfile.TemporaryDirectory() as d:
            binary = os.path.join(d, "ucli")
            _script(binary, 'read x; echo "okunan:$x"')
            r, w = os.pipe()
            os.write(w, b"gizli-girdi\n")
            os.close(w)
            saved = os.dup(0)
            try:
                os.dup2(r, 0)
                ucli_client._HELP_CACHE.clear()
                text = ucli_client.chat_help_text(binary)
                left = os.read(0, 100)
            finally:
                os.dup2(saved, 0)
                os.close(saved)
                os.close(r)
                ucli_client._HELP_CACHE.clear()
            self.assertEqual(text, "okunan:\n")
            self.assertEqual(left, b"gizli-girdi\n")


if __name__ == "__main__":
    unittest.main()

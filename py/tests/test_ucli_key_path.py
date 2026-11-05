"""ucli anahtar dosya yolu TEK yardımcıda (paths.ucli_key_file); çağıranlar ondan türetir."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import paths  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402


class UcliKeyPathTest(unittest.TestCase):
    def test_default_and_service(self):
        base = os.path.expanduser("~/.claude/claudeops")
        self.assertEqual(paths.ucli_key_file(), os.path.join(base, "ucli_api_key"))
        self.assertEqual(paths.ucli_key_file("groq"), os.path.join(base, "ucli_key_groq"))

    def test_callers_share_helper(self):
        self.assertEqual(up._API_KEY_FILE, paths.ucli_key_file())
        self.assertEqual(wr.UCLI_KEY_FILE, paths.ucli_key_file())
        self.assertEqual(up._service_key_file("openrouter"), paths.ucli_key_file("openrouter"))


if __name__ == "__main__":
    unittest.main()

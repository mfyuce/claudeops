"""TBD#144: reviewer Anthropic anahtarı önce byok.ucli.ANTHROPIC_API_KEY, sonra dosya.

Çalıştırma:  python3 py/tests/test_review_anthropic_key.py -v
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_review as wr  # noqa: E402


class AnthropicReviewKey(unittest.TestCase):
    def _file(self, content):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "k")
        if content is not None:
            with open(p, "w") as f:
                f.write(content)
        return p

    def test_byok_wins_over_file(self):
        p = self._file("FILEKEY\n")
        with mock.patch.object(wr, "ANTHROPIC_REVIEW_KEY_FILE", p), \
                mock.patch("claudeops.settings.byok_env_for", return_value={"ANTHROPIC_API_KEY": " BYOK "}):
            self.assertEqual(wr._anthropic_review_key(), "BYOK")

    def test_file_fallback_when_byok_empty(self):
        p = self._file("FILEKEY\n")
        with mock.patch.object(wr, "ANTHROPIC_REVIEW_KEY_FILE", p), \
                mock.patch("claudeops.settings.byok_env_for", return_value={}):
            self.assertEqual(wr._anthropic_review_key(), "FILEKEY")

    def test_none_gives_empty(self):
        p = self._file(None)
        with mock.patch.object(wr, "ANTHROPIC_REVIEW_KEY_FILE", p), \
                mock.patch("claudeops.settings.byok_env_for", return_value={}):
            self.assertEqual(wr._anthropic_review_key(), "")


if __name__ == "__main__":
    unittest.main()

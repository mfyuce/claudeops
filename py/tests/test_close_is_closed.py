"""is_closed_in_models: `cops close`'un bıraktığı `# CLOSED` satırı tespiti (salt okunur, geçici dosya)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import close  # noqa: E402


class IsClosedTest(unittest.TestCase):
    def _tsv(self, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "models.tsv")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_closed_row_detected_for_base_and_full_name(self):
        p = self._tsv("#zlkrn\topus\t# CLOSED\nuipol\tsonnet\n")
        self.assertTrue(close.is_closed_in_models("zlkrn", p))
        self.assertTrue(close.is_closed_in_models("zlkrn2", p))

    def test_active_row_wins_and_plain_comment_is_not_closed(self):
        p = self._tsv("#zlkrn\topus\t# CLOSED\nzlkrn\topus\n#cli\topus\n")
        self.assertFalse(close.is_closed_in_models("zlkrn", p))
        self.assertFalse(close.is_closed_in_models("cli", p))

    def test_missing_file_is_false(self):
        self.assertFalse(close.is_closed_in_models("x", "/nonexistent/models.tsv"))


if __name__ == "__main__":
    unittest.main()

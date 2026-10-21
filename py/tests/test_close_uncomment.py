import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops.commands import close  # noqa: E402


class UncommentModelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "models.tsv")
        self._old = close.MODELS_TSV
        close.MODELS_TSV = self.path

    def tearDown(self):
        close.MODELS_TSV = self._old
        self.tmp.cleanup()

    def _write(self, text):
        open(self.path, "w", encoding="utf-8").write(text)

    def test_roundtrip_with_comment_out(self):
        self._write("mkt\tsonnet\tmedium\nzlkrn\topus\thigh\n")
        self.assertEqual(close.comment_out_models("mkt", False), "commented")
        self.assertEqual(close.uncomment_models("mkt", True), "restored")      # kuru: dosya değişmez
        self.assertIn("# CLOSED", open(self.path).read())
        self.assertEqual(close.uncomment_models("mkt"), "restored")
        self.assertEqual(open(self.path).read(), "mkt\tsonnet\tmedium\nzlkrn\topus\thigh\n")
        self.assertEqual(close.uncomment_models("mkt"), "active")

    def test_hand_commented_line_untouched(self):
        self._write("#mkt\tsonnet\tmedium\n")
        self.assertEqual(close.uncomment_models("mkt"), "notfound")
        self.assertEqual(open(self.path).read(), "#mkt\tsonnet\tmedium\n")


if __name__ == "__main__":
    unittest.main()

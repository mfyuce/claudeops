"""ucli'ye giden çok satırlı metin tek satıra iner (TODO: ÇOK SATIRLI MESAJ DÜZELTMESİ).

Çalıştırma:  python3 py/tests/test_ucli_multiline_flatten.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.providers import get_provider  # noqa: E402


class FlattenTest(unittest.TestCase):
    def test_ucli_flattens(self):
        p = get_provider("ucli")
        self.assertEqual(p.prepare_input("a\nb\n\n  c  \r\nd\re"), "a b c d e")

    def test_ucli_single_line_unchanged(self):
        p = get_provider("ucli")
        self.assertEqual(p.prepare_input("  tek satır  "), "  tek satır  ")

    def test_ucli_trailing_newline(self):
        self.assertEqual(get_provider("ucli").prepare_input("x\n"), "x")

    def test_other_providers_untouched(self):
        for cli in ("claude", "codex"):
            self.assertEqual(get_provider(cli).prepare_input("a\nb"), "a\nb")


if __name__ == "__main__":
    unittest.main()

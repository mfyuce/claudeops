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

    def test_ucli_tab_single_line(self):
        self.assertEqual(get_provider("ucli").prepare_input("a\tb\t\tc  d"), "a b c d")

    def test_ucli_long_text_not_truncated(self):
        long = "bir\n" + ("uzun " * 400) + "\nson"
        out = get_provider("ucli").prepare_input(long)
        self.assertNotIn("\n", out)
        self.assertTrue(out.startswith("bir uzun"))
        self.assertTrue(out.endswith("son"))
        self.assertGreater(len(out), 2000)

    def test_single_fold_point_in_callers(self):
        # katlama kopyaları kaldırıldı: handover.py ve web_steward._send artık kendileri katlamaz
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ("claudeops/handover.py",):
            src = open(os.path.join(base, rel), encoding="utf-8").read()
            self.assertNotIn('" ".join(str(message or "").split())', src)

    def test_other_providers_untouched(self):
        for cli in ("claude", "codex"):
            self.assertEqual(get_provider(cli).prepare_input("a\nb"), "a\nb")


if __name__ == "__main__":
    unittest.main()

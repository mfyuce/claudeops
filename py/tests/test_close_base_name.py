"""review R-1 (P1): close.py'nin taban-ad regex'i session.py/rc.py ile ayrışmıştı; artık TEK kaynak."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import session  # noqa: E402
from claudeops.commands import close, rc  # noqa: E402


class BaseName(unittest.TestCase):
    def test_single_source(self):
        self.assertIs(close._BASE_RE, session._NAME_RE)
        self.assertIs(rc._NAME_RE, session._NAME_RE)

    def test_date_and_conflict_suffixes_reduce(self):
        for name, base in (("cli_2", "cli"), ("cops20260824_1", "cops"), ("hc58", "hc"), ("mo20260813_1", "mo"), ("carla", "carla")):
            self.assertEqual(close._base(name), base, name)


if __name__ == "__main__":
    unittest.main()


class TsvFinder(unittest.TestCase):
    """review R-2 (P1): web.py'deki iki TSV satır bulucu kopyası TEK `_find_tsv_line`; davranış aynı."""

    def test_find_and_edit(self):
        import tempfile
        from claudeops.commands import web
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "models.tsv")
            open(p, "w", encoding="utf-8").write("# header\nhc\tdir\tm\n#old\tdir\tm\nzz\tx\ty\n")
            self.assertEqual(web._find_tsv_line(open(p).readlines(), "hc")[:2], (1, False))
            self.assertEqual(web._find_tsv_line(open(p).readlines(), "old")[:2], (2, True))
            self.assertIsNone(web._find_tsv_line(open(p).readlines(), "yok"))
            self.assertTrue(web._toggle_comment_unlocked(p, "hc", want_active=False))
            self.assertIn("#hc\tdir\tm\n", open(p).read())
            self.assertTrue(web._toggle_comment_unlocked(p, "old", want_active=True))
            self.assertIn("\nold\tdir\tm\n", open(p).read())
            self.assertTrue(web._replace_tsv_line_unlocked(p, "zz", ["zz2", "a", "b"]))
            self.assertIn("\nzz2\ta\tb\n", open(p).read())
            self.assertFalse(web._toggle_comment_unlocked(p, "yok", want_active=True))
            self.assertFalse(web._replace_tsv_line_unlocked(p, "yok", ["a"]))

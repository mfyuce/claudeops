"""Fable review dizini (FABLE-INDEX.md): ciddiyet sayımı rapor biçimine uyar, [x] korunur, rapor/.io.jsonl silinmez, saklama Fable .io.jsonl'i de alır."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review_store as rs  # noqa: E402

REPORT = "# Rapor\n\n## R-1 | P2 | a.py:1 | bir\ntext\n## R-2 | P3 | b.py:2 | iki\n## R-3 | P3 | c.py:3 | üç\n"


def _mk(root, rel, text):
    fp = os.path.join(root, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(text)
    return fp


class FableIndexTest(unittest.TestCase):
    def test_severity_counts_match_report_format(self):
        self.assertEqual(rs.severity_counts(REPORT), {"P2": 1, "P3": 2})
        self.assertEqual(rs.severity_counts("hiç bulgu yok"), {})

    def test_index_lists_only_fable_and_counts(self):
        with tempfile.TemporaryDirectory() as d:
            _mk(d, "au/claude/claude-fable-5-2/low/20261117130340/20261117130340.md", REPORT)
            _mk(d, "au/agy/gemini-3.8-flash-medium/default/20261117130341/20261117130341.md", REPORT)   # Fable değil
            self.assertTrue(rs.write_fable_index(d))
            txt = open(os.path.join(d, "FABLE-INDEX.md"), encoding="utf-8").read()
            self.assertIn("P2:1 P3:2", txt)
            self.assertIn("fable-5-2 low", txt)
            self.assertNotIn("gemini", txt)
            self.assertFalse(rs.write_fable_index(d))       # içerik aynı: yeniden yazılmaz

    def test_read_marks_survive_regeneration(self):
        with tempfile.TemporaryDirectory() as d:
            rel = "au/claude/claude-fable-5-2-sub/high/20261117135945/20261117135945.md"
            _mk(d, rel, REPORT)
            rs.write_fable_index(d)
            p = os.path.join(d, "FABLE-INDEX.md")
            t = open(p, encoding="utf-8").read().replace("- [ ]", "- [x]")
            open(p, "w", encoding="utf-8").write(t)
            _mk(d, "au/claude/claude-fable-5-2-sub/low/20261117135159/20261117135159.md", REPORT)   # yeni rapor
            rs.write_fable_index(d)
            t2 = open(p, encoding="utf-8").read()
            self.assertEqual(t2.count("- [x]"), 1)        # eskisi okundu kaldı
            self.assertEqual(t2.count("- [ ]"), 1)        # yenisi okunmadı

    def test_no_fable_no_index(self):
        with tempfile.TemporaryDirectory() as d:
            _mk(d, "au/agy/m/default/20261117130341/20261117130341.md", REPORT)
            self.assertFalse(rs.write_fable_index(d))
            self.assertFalse(os.path.exists(os.path.join(d, "FABLE-INDEX.md")))

    def test_is_fable_path(self):
        self.assertTrue(rs.is_fable_path("au/claude/claude-fable-5-2/low/1/1.md"))
        self.assertFalse(rs.is_fable_path("au/claude/claude-haiku-5-5/low/1/1.md"))


class FableNeverDeletedTest(unittest.TestCase):
    def test_remove_streams_keeps_report_and_io(self):
        from claudeops.commands import web_review
        with tempfile.TemporaryDirectory() as d:
            md = _mk(d, "20261117130340.md", REPORT)
            io = _mk(d, "20261117130340.io.jsonl", "{}\n")
            raw = _mk(d, "20261117130340.stdout", "ham")
            web_review._remove_streams(md)
            self.assertTrue(os.path.exists(md))
            self.assertTrue(os.path.exists(io))
            self.assertFalse(os.path.exists(raw))        # yalnız ham akış silinir


if __name__ == "__main__":
    unittest.main()


class CommitModifiedIndexTest(unittest.TestCase):
    """İzlenen FABLE-INDEX.md değişince yeniden commit edilir (diğer izlenen dosyalar eskisi gibi atlanır)."""

    def test_modified_tracked_index_committed(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root, gd = os.path.join(d, "w"), os.path.join(d, "g.git")
            os.makedirs(root)
            subprocess.run(["git", "init", "-q", "--bare", gd], check=True)
            _mk(root, "reviews/au/claude/claude-fable-5-2/low/20261117130340/20261117130340.md", REPORT)
            rs.write_fable_index(os.path.join(root, "reviews"))
            ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
            import claudeops.review_store as m
            real = m._git
            m._git = lambda base, *a, run=None, timeout=120.0: real(base[:1] + ident + base[1:], *a, run=run, timeout=timeout)
            try:
                r1 = rs.commit_reviews(root, gd, lambda t: t, dry=False, vis_check=lambda g: "private")
                self.assertEqual(r1["committed"], 2, r1)        # rapor + indeks
                _mk(root, "reviews/au/claude/claude-fable-5-2/high/20261117131157/20261117131157.md", REPORT)
                rs.write_fable_index(os.path.join(root, "reviews"))
                r2 = rs.commit_reviews(root, gd, lambda t: t, dry=False, vis_check=lambda g: "private")
                self.assertEqual(r2["committed"], 2, r2)        # yeni rapor + DEĞİŞEN izlenen indeks
                r3 = rs.commit_reviews(root, gd, lambda t: t, dry=False, vis_check=lambda g: "private")
                self.assertEqual(r3["committed"], 0, r3)
            finally:
                m._git = real

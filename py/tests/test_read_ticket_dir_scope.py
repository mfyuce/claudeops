"""read_ticket dizin kapsamı: belge adı + belge dizini altındaki YALNIZ resimler; traversal/mutlak/resim dışı reddedilir."""
import unittest

from claudeops import read_ticket as rt


class ResolveUrlPathTest(unittest.TestCase):
    DOC = "/proj/belge/ana.tex"

    def test_doc_name_returns_doc(self):
        self.assertEqual(rt.resolve_url_path(self.DOC, "ana.tex"), self.DOC)
        self.assertEqual(rt.resolve_url_path("/p/Türkçe ad.md", "T%C3%BCrk%C3%A7e%20ad.md"), "/p/Türkçe ad.md")

    def test_image_under_doc_dir(self):
        self.assertEqual(rt.resolve_url_path(self.DOC, "figs/a.PNG"), "/proj/belge/figs/a.PNG")
        self.assertEqual(rt.resolve_url_path(self.DOC, "a%20b.jpg"), "/proj/belge/a b.jpg")

    def test_rejects(self):
        for bad in ("../x.png", "figs/../../x.png", "%2e%2e/x.png", "/etc/x.png", "figs//x.png", "./x.png", "a\\b.png",
                    "gizli.txt", "figs/x.pdf", "x.tex", "", "x.png%00.txt", "figs/"):
            self.assertIsNone(rt.resolve_url_path(self.DOC, bad), bad)

    def test_other_doc_name_not_readable(self):
        self.assertIsNone(rt.resolve_url_path(self.DOC, "baska.tex"))


if __name__ == "__main__":
    unittest.main()

"""review cops ayıklaması: finding_key Markdown bağlantılı `where` (R-3 20261108205712), is_conditional_note Türkçe koşul kalıpları (R-1 20261107152517)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review, steward as sw  # noqa: E402


class FindingKeyTest(unittest.TestCase):
    def test_markdown_link_where_same_key_as_plain(self):
        plain = review.finding_key("p", "py/claudeops/hosts.py:196", "Aynı hata")
        for w in ("[py/claudeops/hosts.py:196](file:///home/x/py/claudeops/hosts.py#L180-L208)",
                  "[`py/claudeops/hosts.py`](file:///h/py/claudeops/hosts.py#L1)", "`py/claudeops/hosts.py`:196", "./py/claudeops/hosts.py#L3"):
            self.assertEqual(review.finding_key("p", w, "Aynı hata"), plain, w)

    def test_different_file_or_title_differs(self):
        a = review.finding_key("p", "a.py:1", "x")
        self.assertNotEqual(a, review.finding_key("p", "[b.py:1](file:///b.py)", "x"))
        self.assertNotEqual(a, review.finding_key("p", "a.py:1", "y"))


class ConditionalNoteTest(unittest.TestCase):
    def test_turkish_conditions(self):
        for t in ("dosya varsa onu işle", "yoksa yeni dosya aç", "testler yeşil olsa devam", "sahip cevap verirse devam", "kural değilse atla",
                  "yapılmazsa atla", "olmazsa bekle"):
            self.assertTrue(sw.is_conditional_note(t), t)
        for t in ("tüm testleri yaz", "ucli sid'i taşı", "dokümanı güncelle"):
            self.assertFalse(sw.is_conditional_note(t), t)


if __name__ == "__main__":
    unittest.main()

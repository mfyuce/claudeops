"""web._content_disposition: Latin-1 dışı dosya adı başlığı bozmaz (filename= salt ASCII, filename*= UTF-8)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


class ContentDispositionTest(unittest.TestCase):
    def test_turkish_name_is_ascii_safe_and_latin1_encodable(self):
        h = web._content_disposition("rapor şğıİ.md")
        h.encode("latin-1")                      # send_header'ın yaptığı kodlama çökmemeli
        self.assertIn('filename="rapor ____.md"', h)
        self.assertIn("filename*=UTF-8''rapor%20%C5%9F%C4%9F%C4%B1%C4%B0.md", h)

    def test_quotes_and_newlines_are_stripped(self):
        h = web._content_disposition('a"b\r\nc.txt')
        self.assertNotIn("\r", h)
        self.assertNotIn("\n", h)
        self.assertIn('filename="a_b__c.txt"', h)

    def test_empty_name_falls_back(self):
        self.assertIn('filename="download"', web._content_disposition(""))


if __name__ == "__main__":
    unittest.main()

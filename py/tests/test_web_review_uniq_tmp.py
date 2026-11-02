"""web_review.py: sabit `<yol>.tmp` adı yok (eşzamanlı yazarlar birbirinin tmp'sini ezmesin) — P4-VERDICT #4."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_review  # noqa: E402


class UniqTmpTest(unittest.TestCase):
    def test_uniq_tmp_differs_and_keeps_dir(self):
        a, b = web_review._uniq_tmp("/x/y.json"), web_review._uniq_tmp("/x/y.json")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("/x/y.json.") and a.endswith(".tmp"))

    def test_no_fixed_tmp_names_in_source(self):
        src = open(web_review.__file__, encoding="utf-8").read()
        self.assertEqual(re.findall(r'=\s*[^\n]*\+\s*"\.tmp"', src), [])
        self.assertNotIn('"settings.json.tmp"', src)


if __name__ == "__main__":
    unittest.main()

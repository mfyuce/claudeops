"""GATE-TODO4 madde 7: dist acilis kontrolu (gecici dizin; gercek dist'e dokunmaz).
Calistirma: python3 -m unittest discover -s py/tests"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import dist_check as dc  # noqa: E402

INDEX = '<html><script src="/assets/app-1.js"></script><link href="/assets/app-1.css" rel="stylesheet"></html>'


class TestDistCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name
        os.makedirs(os.path.join(self.d, "assets"))

    def write(self, rel, text="x"):
        with open(os.path.join(self.d, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def test_referenced_assets_parsed(self):
        self.assertEqual(dc.referenced_assets(INDEX), ["assets/app-1.js", "assets/app-1.css"])

    def test_all_present_is_ok_and_not_logged(self):
        self.write("index.html", INDEX)
        self.write("assets/app-1.js")
        self.write("assets/app-1.css")
        calls = []
        res = dc.log_if_missing(lambda *a, **k: calls.append((a, k)), self.d)
        self.assertTrue(res["ok"])
        self.assertEqual(calls, [])

    def test_missing_bundle_is_logged_as_dist_eksik(self):
        self.write("index.html", INDEX)
        self.write("assets/app-1.js")
        calls = []
        res = dc.log_if_missing(lambda *a, **k: calls.append((a, k)), self.d)
        self.assertFalse(res["ok"])
        self.assertEqual(res["missing"], ["assets/app-1.css"])
        self.assertEqual(calls[0][0], ("dist-eksik",))
        self.assertEqual(calls[0][1]["missing"], ["assets/app-1.css"])

    def test_missing_index_reported(self):
        res = dc.check_dist(self.d)
        self.assertFalse(res["ok"])
        self.assertEqual(res["missing"], ["index.html"])


if __name__ == "__main__":
    unittest.main()

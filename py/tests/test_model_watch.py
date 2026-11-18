import json
import os
import tempfile
import unittest

from claudeops import model_watch as mw


class CompareTests(unittest.TestCase):
    def test_baseline_has_no_new(self):
        r = mw.compare(None, {"agy": ["a", "b"]}, 1.0)
        self.assertEqual(r["new"], {})
        self.assertEqual(r["catalog"]["providers"]["agy"]["models"], {"a": "present", "b": "present"})

    def test_new_and_gone(self):
        prev = mw.compare(None, {"agy": ["a", "b"]}, 1.0)["catalog"]
        r = mw.compare(prev, {"agy": ["a", "c"]}, 2.0)
        self.assertEqual(r["new"], {"agy": ["c"]})
        self.assertEqual(r["gone"], {"agy": ["b"]})
        self.assertEqual(r["catalog"]["providers"]["agy"]["models"]["b"], "gone")

    def test_empty_scan_keeps_record_and_no_gone(self):
        prev = mw.compare(None, {"agy": ["a"]}, 1.0)["catalog"]
        r = mw.compare(prev, {"agy": []}, 2.0)
        self.assertEqual(r["gone"], {})
        self.assertEqual(r["catalog"]["providers"]["agy"]["models"], {"a": "present"})

    def test_new_provider_after_baseline_is_baseline_for_it(self):
        prev = mw.compare(None, {"agy": ["a"]}, 1.0)["catalog"]
        r = mw.compare(prev, {"agy": ["a"], "codex": ["x"]}, 2.0)
        self.assertEqual(r["new"], {})

    def test_run_persists_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cat.json")
            f1 = lambda n: ["a"] if n == "agy" else []
            self.assertTrue(mw.run(p, f1, 1.0)["baseline"])
            f2 = lambda n: ["a", "z"] if n == "agy" else []
            r = mw.run(p, f2, 2.0)
            self.assertEqual(r["new"], {"agy": ["z"]})
            self.assertEqual(json.load(open(p))["providers"]["agy"]["models"]["z"], "present")


if __name__ == "__main__":
    unittest.main()

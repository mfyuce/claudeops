import unittest
from claudeops.commands import web_hosts


class OrphanBriefTest(unittest.TestCase):
    def test_brief(self):
        self.assertEqual(web_hosts._orphan_brief({"servers": 2, "procs": "3", "detail": {"x": 1}, "last_end": 5}),
                         {"servers": 2, "procs": 3, "last_end": 5})
        self.assertIsNone(web_hosts._orphan_brief(None))
        self.assertIsNone(web_hosts._orphan_brief({"servers": "x"}))


if __name__ == "__main__":
    unittest.main()


class FwdBriefTest(unittest.TestCase):
    def test_brief(self):
        r = web_hosts._fwd_brief({"api": 1, "mode": "require", "kids": ["a1", "b2"], "now": 1010.5}, 1000.0)
        self.assertEqual(r, {"mode": "require", "kids": ["a1", "b2"], "skew": 10.5})
        self.assertEqual(web_hosts._fwd_brief({"mode": "accept"}, 1.0), {"mode": "accept", "kids": [], "skew": None})
        self.assertIsNone(web_hosts._fwd_brief(None, 1.0))
        self.assertIsNone(web_hosts._fwd_brief({"now": "x"}, 1.0))

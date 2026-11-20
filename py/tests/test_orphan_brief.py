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


class WsFrameTest(unittest.TestCase):
    def test_ws_frame_keeps_host_badges(self):
        import json
        frame = json.dumps({"type": "status", "data": {"sessions": [], "disk_clean": {"pct": 50}, "orphan_watch": {"servers": 1, "procs": 0},
                                                       "fwd": {"mode": "accept", "kids": ["a"], "now": 5.0}}})
        r = web_hosts._finalize_remote_result("h", web_hosts._parse_ws_status_frame(frame))
        self.assertEqual(r["disk_clean"], {"pct": 50})
        self.assertEqual(r["orphan_watch"]["servers"], 1)
        self.assertEqual(r["fwd"]["mode"], "accept")

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


class GrpcExtrasTest(unittest.TestCase):
    def test_roundtrip_extras(self):
        from claudeops.commands import web_grpc
        d = {"sessions": [], "closed": [], "retired": [], "cli_list": [], "cli_options": {}, "dups": [],
             "disk_clean": {"pct": 61}, "orphan_watch": {"servers": 1, "procs": 2}, "fwd": {"mode": "require", "kids": ["a"], "now": 9.5}}
        back = web_grpc._status_proto_to_dict(web_grpc._status_dict_to_proto(d))
        self.assertEqual(back["disk_clean"], {"pct": 61})
        self.assertEqual(back["orphan_watch"], {"servers": 1, "procs": 2})
        self.assertEqual(back["fwd"]["mode"], "require")
        r = web_hosts._finalize_remote_result("h", back)
        self.assertEqual(r["fwd"]["kids"], ["a"])

    def test_no_extras_is_clean(self):
        from claudeops.commands import web_grpc
        back = web_grpc._status_proto_to_dict(web_grpc._status_dict_to_proto({"sessions": []}))
        self.assertNotIn("fwd", back)


class BuildRunningTest(unittest.TestCase):
    def test_build_running(self):
        self.assertEqual(web_hosts._build_running({"running": "abcdef1234567890", "disk": "x"}), "abcdef123456")
        self.assertIsNone(web_hosts._build_running(None))
        self.assertIsNone(web_hosts._build_running({"running": ""}))
        r = web_hosts._finalize_remote_result("h", {"ok": True, "build": {"running": "abc123"}})
        self.assertEqual(r["build_running"], "abc123")

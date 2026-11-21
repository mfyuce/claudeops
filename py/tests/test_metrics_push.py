"""Periyodik iş -> copsd metrik göndericisi: nokta biçimi, sahte sunucuya POST (X-Cops-Front), hata yutma. Canlı servis YOK."""
import http.server
import json
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import metrics_push as mp  # noqa: E402


class Build(unittest.TestCase):
    def test_points(self):
        pts = mp.build_points("host_probe", 12.34, {"ok": True, "hosts": 3, "msg": "x", "flag": True, "bad": float("nan")}, 100.0)
        keys = {p["key"]: p["value"] for p in pts}
        self.assertEqual(keys, {"ms": 12.3, "ok": 1, "hosts": 3})
        self.assertTrue(all(p["name"] == "job.host_probe" and p["ts"] == 100.0 for p in pts))
        self.assertEqual({p["key"]: p["value"] for p in mp.build_points("a", 1, {"ok": False}, 1.0)}["ok"], 0)

    def test_cap_numeric_fields(self):
        pts = mp.build_points("a", 1, {f"k{i}": i for i in range(40)}, 1.0)
        self.assertEqual(len(pts), 2 + 12)


class Post(unittest.TestCase):
    def test_posts_with_front_secret_and_swallows_errors(self):
        got = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                got["path"], got["front"] = self.path, self.headers.get("X-Cops-Front")
                got["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        pts = mp.build_points("j", 5, {"ok": True}, 1.0)
        with mock.patch.object(mp.front, "read_secret", lambda: "s3"), mock.patch.object(mp, "ADDR", "127.0.0.1:%d" % srv.server_port):
            mp._post(pts)
        srv.shutdown()
        self.assertEqual(got["path"], "/api/metrics/points")
        self.assertEqual(got["front"], "s3")
        self.assertEqual(got["body"][0]["name"], "job.j")
        with mock.patch.object(mp.front, "read_secret", lambda: "s3"), mock.patch.object(mp, "ADDR", "127.0.0.1:1"):
            mp._post(pts)                       # kapalı port: fırlatmaz
        with mock.patch.object(mp.front, "read_secret", lambda: ""):
            mp._post(pts)                       # gizli yok: sessizce atlanır


if __name__ == "__main__":
    unittest.main()

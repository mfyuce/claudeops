"""RemoteReviewDriver.export_file: okuma -> tekrar oku -> files/write -> doğrula -> bildirim (stdlib unittest; ağ YOK)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class T(unittest.TestCase):
    def setUp(self):
        self.files = {"/r/p/TODO.md": "# TODO\n"}
        self.posts = []
        drv = ws.RemoteReviewDriver("p", "h1")
        self.drv = drv

        def post(host, path, body, timeout, *a, **k):
            self.posts.append((path, body))
            if path == "/api/files/write":
                if self.fail_write:
                    return {"ok": False, "error": "boom"}
                self.files[body["path"]] = body["content"]
            return {"ok": True}

        self.fail_write = False
        self.busy = False
        for pt in (mock.patch.object(drv, "ready", lambda: (True, "")),
                   mock.patch.object(ws, "_remote_files_gate", lambda h, sid="default": True),
                   mock.patch.object(drv, "_owner", lambda: "default"),
                   mock.patch.object(ws, "_remote_ref", lambda h, n: ("p", "/r/p")),
                   mock.patch.object(ws, "_remote_read_full", lambda h, n, path, b: self.files.get(path)),
                   mock.patch.object(ws, "_remote_post", post),
                   mock.patch.object(ws, "_remote_running_row", lambda h, n, rt=None: (True, {"name": n, "busy": self.busy}))):
            pt.start()
            self.addCleanup(pt.stop)

    def build(self, text):
        return text + "- yeni\n", ["F1"]

    def test_write_verify_notify(self):
        r = self.drv.export_file("TODO.md", self.build, "merhaba")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.files["/r/p/TODO.md"], "# TODO\n- yeni\n")
        self.assertTrue(r["session_open"] and r["notified"])
        self.assertEqual([p for p, _ in self.posts], ["/api/files/write", "/api/term/input"])

    def test_busy_session_not_notified(self):
        self.busy = True
        r = self.drv.export_file("TODO.md", self.build, "merhaba")
        self.assertTrue(r["ok"] and not r["notified"])
        self.assertEqual([p for p, _ in self.posts], ["/api/files/write"])

    def test_missing_file_stops_without_write(self):
        del self.files["/r/p/TODO.md"]
        r = self.drv.export_file("TODO.md", self.build)
        self.assertFalse(r["ok"])
        self.assertEqual(self.posts, [])

    def test_write_failure_reported(self):
        self.fail_write = True
        r = self.drv.export_file("TODO.md", self.build)
        self.assertFalse(r["ok"])
        self.assertIn("write_failed", r["error"])

    def test_nothing_new_no_write(self):
        r = self.drv.export_file("TODO.md", lambda t: (None, []))
        self.assertTrue(r["ok"] and r["written"] == [])
        self.assertEqual(self.posts, [])

    def test_bad_filename(self):
        self.assertFalse(self.drv.export_file("../x", self.build)["ok"])


if __name__ == "__main__":
    unittest.main()

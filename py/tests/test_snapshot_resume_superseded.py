"""863: `_snapshot_resume` aynı türev taban + aynı cwd'de canlı session varken eski instance'ı DİRİLTMEZ (hepsi sahte; süreç/disk YOK)."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


class SnapshotResumeSupersededTest(unittest.TestCase):
    def _run(self, entries, live):
        started = []

        def fake_start(name, **kw):
            started.append(name)
            return {"ok": True}

        with mock.patch.object(web, "load_latest_snapshot", lambda: {"sessions": entries}), \
                mock.patch.object(web, "normalize_mirrors", lambda m: []), \
                mock.patch.object(web, "_fleet_status", lambda: {n: {"state": "active"} for n in
                                                                  [e["name"] for e in entries]}), \
                mock.patch.object(web, "find_sessions", lambda measure_cpu=False: live), \
                mock.patch.object(web, "_start", fake_start), \
                mock.patch.object(web, "_snapshot_resume_mirrors", lambda *a, **k: []):
            res = web._snapshot_resume()
        return res, started

    def test_older_instance_same_cwd_is_superseded(self):
        entries = [{"name": "oiso20261001", "cwd": "/w/oiso"}]
        live = [SimpleNamespace(name="oiso20261017", cwd="/w/oiso")]
        res, started = self._run(entries, live)
        self.assertEqual(started, [])
        self.assertEqual(res["results"][0]["status"], "already_running")
        self.assertTrue(res["results"][0].get("superseded"))

    def test_different_cwd_still_starts(self):
        entries = [{"name": "oiso20261001", "cwd": "/w/oiso"}]
        live = [SimpleNamespace(name="oiso20261017", cwd="/w/baska")]
        res, started = self._run(entries, live)
        self.assertEqual(started, ["oiso20261001"])
        self.assertEqual(res["started"], 1)

    def test_different_base_same_cwd_still_starts(self):
        entries = [{"name": "oiso20261001", "cwd": "/w/x"}]
        live = [SimpleNamespace(name="kitap20261017", cwd="/w/x")]
        _, started = self._run(entries, live)
        self.assertEqual(started, ["oiso20261001"])


if __name__ == "__main__":
    unittest.main()

"""web_review.pool_action `only` ("Yalnız bu"): tek kilit/tek kayıtla hedef açık, diğerleri kapalı; kapatılanların işi iptal edilir."""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import review as rv  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402


class TestPoolOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = SimpleNamespace(sid="default")
        self.cancelled = []
        for p in (mock.patch.object(sw, "STEWARD_DIR", self.tmp.name),
                  mock.patch.object(wr, "ownership", lambda: {"owners": {}}),
                  mock.patch.object(wr, "remote_block_reason", lambda *a, **k: ""),
                  mock.patch.object(wr, "cancel_all", lambda sid, proj: self.cancelled.append(proj) or [proj])):
            p.start()
            self.addCleanup(p.stop)
        with open(sw.paths_for("default").review_pool, "w", encoding="utf-8") as f:
            json.dump({"projects": {
                "a": {"enabled": True, "source": "manual", "focus": True},
                "b": {"enabled": True, "source": "manual"},
                "c": {"enabled": False, "source": "manual"},
            }}, f)

    def pool(self):
        return rv.load_pool(sw.paths_for("default"))["projects"]

    def test_only_enables_target_disables_rest_atomically(self):
        r = wr.pool_action(self.cfg, "only", "c")
        self.assertTrue(r["ok"], r)
        self.assertEqual(sorted(r["disabled"]), ["a", "b"])
        pr = self.pool()
        self.assertEqual([k for k, v in pr.items() if v.get("enabled")], ["c"])
        self.assertNotIn("focus", pr["a"])
        self.assertEqual(sorted(self.cancelled), ["a", "b"])

    def test_only_unknown_project_changes_nothing(self):
        r = wr.pool_action(self.cfg, "only", "nope")
        self.assertFalse(r["ok"])
        self.assertEqual(sorted(k for k, v in self.pool().items() if v.get("enabled")), ["a", "b"])
        self.assertEqual(self.cancelled, [])

    def test_only_remote_block_refuses_before_any_change(self):
        with mock.patch.object(wr, "remote_block_reason", lambda *a, **k: "blocked"):
            r = wr.pool_action(self.cfg, "only", "c")
        self.assertFalse(r["ok"])
        self.assertEqual(sorted(k for k, v in self.pool().items() if v.get("enabled")), ["a", "b"])


if __name__ == "__main__":
    unittest.main()

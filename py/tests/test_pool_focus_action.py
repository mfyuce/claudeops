"""web_review.pool_action focus/unfocus (ODAK anahtarı) — stdlib unittest, geçici dizinde.

Çalıştırma:  python3 py/tests/test_pool_focus_action.py -v
"""
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


class TestPoolFocusAction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = SimpleNamespace(sid="default")
        patches = [
            mock.patch.object(sw, "STEWARD_DIR", self.tmp.name),
            mock.patch.object(wr, "ownership", lambda: {"owners": {}}),
            mock.patch.object(wr, "remote_block_reason", lambda *a, **k: ""),
            mock.patch.object(wr, "cancel_all", lambda *a, **k: []),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        path = sw.paths_for("default").review_pool
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"projects": {
                "on": {"enabled": True, "source": "manual"},
                "off": {"enabled": False, "source": "manual"},
            }}, f)

    def _pool(self):
        return rv.load_pool(sw.paths_for("default"))["projects"]

    def test_focus_then_unfocus(self):
        r = wr.pool_action(self.cfg, "focus", "on")
        self.assertTrue(r["ok"], r)
        self.assertTrue(self._pool()["on"].get("focus"))
        self.assertEqual(rv.pool_focus({"projects": self._pool()}), ["on"])
        r = wr.pool_action(self.cfg, "unfocus", "on")
        self.assertTrue(r["ok"], r)
        self.assertNotIn("focus", self._pool()["on"])

    def test_focus_needs_enabled_project(self):
        r = wr.pool_action(self.cfg, "focus", "off")
        self.assertFalse(r["ok"])
        self.assertNotIn("focus", self._pool()["off"])

    def test_focus_unknown_project(self):
        r = wr.pool_action(self.cfg, "focus", "nope")
        self.assertFalse(r["ok"])

    def test_disable_and_remove_clear_focus(self):
        for act in ("disable", "remove"):
            with self.subTest(act=act):
                wr.pool_action(self.cfg, "enable", "on")
                wr.pool_action(self.cfg, "focus", "on")
                self.assertTrue(wr.pool_action(self.cfg, act, "on")["ok"])
                e = self._pool().get("on") or {}
                self.assertNotIn("focus", e)


if __name__ == "__main__":
    unittest.main()

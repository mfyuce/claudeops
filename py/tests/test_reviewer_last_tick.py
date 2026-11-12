"""Reviewer kimliği: motor tick_once çalıştırmaz, `last_tick` yine de güncellenmeli (status "8g" göstermesin)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class ReviewerLastTick(unittest.TestCase):
    def test_marks_last_tick(self):
        store = {}
        with mock.patch.object(ws.sw, "paths_for", lambda sid: "P:" + sid), \
             mock.patch.object(ws.sw, "load_state", lambda p: dict(store.get(p, {"x": 1}))), \
             mock.patch.object(ws.sw, "save_state", lambda st, p: store.__setitem__(p, st)):
            ws._mark_reviewer_tick("reviewer", now=123.0)
        self.assertEqual(store["P:reviewer"]["last_tick"], 123.0)
        self.assertEqual(store["P:reviewer"]["x"], 1)      # öteki alanlar korunur

    def test_drops_fossil_tour_fields(self):
        store = {"P:reviewer": {"pending_items": 3, "pending_list": [{"kind": "blocked"}], "blocked_tours": {"q": 1}, "x": 1}}
        with mock.patch.object(ws.sw, "paths_for", lambda sid: "P:" + sid), \
             mock.patch.object(ws.sw, "load_state", lambda p: dict(store.get(p, {}))), \
             mock.patch.object(ws.sw, "save_state", lambda st, p: store.__setitem__(p, st)):
            ws._mark_reviewer_tick("reviewer", now=5.0)
        self.assertEqual(store["P:reviewer"], {"x": 1, "last_tick": 5.0})

    def test_failure_does_not_raise(self):
        with mock.patch.object(ws.sw, "paths_for", side_effect=RuntimeError("boom")), \
             mock.patch.object(ws.sw, "log_event") as le:
            ws._mark_reviewer_tick("reviewer")
        self.assertTrue(le.called)


if __name__ == "__main__":
    unittest.main()

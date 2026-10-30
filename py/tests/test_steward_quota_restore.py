"""Kota bekçisi seviyesi servis restart'ında `quota.json`dan geri yüklenir: ilk yoklama aynı seviyeyi YENİ yükseliş sanıp
oturumları yeniden kapatmaz (TODO 2026-10-28 (21) A)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward_quota as sq  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class QuotaRestoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.qf = os.path.join(self.tmp, "quota.json")
        self.saved = dict(ws._QUOTA)
        ws._QUOTA.update(level=0, stopped=False, loaded=False, decision=None, usage=None, busy=True)
        self.addCleanup(lambda: (ws._QUOTA.clear(), ws._QUOTA.update(self.saved)))

    def _poll(self, action):
        stops = []
        with mock.patch.object(ws.sw, "log_event", lambda *a, **k: None), \
                mock.patch.object(ws, "QUOTA_FILE", self.qf), \
                mock.patch.object(ws, "quota_read_usage", lambda: sq.Usage(week_pct=95.0) if hasattr(sq, "Usage") else object()), \
                mock.patch.object(ws, "quota_config", lambda: {}), \
                mock.patch.object(ws.sq, "decide", lambda cfg, u, now: sq.Decision(action=action, reason="t")), \
                mock.patch.object(ws, "_quota_stop", lambda reason, hard=False: stops.append((reason, hard))):
            ws._quota_restore()
            ws._quota_poll()
        return stops

    def test_restart_at_same_level_does_not_stop_again(self):
        with open(self.qf, "w") as f:
            json.dump({"decision": {"action": "shutdown"}}, f)
        self.assertEqual(self._poll("shutdown"), [])

    def test_higher_level_after_restart_still_stops(self):
        with open(self.qf, "w") as f:
            json.dump({"decision": {"action": "shutdown"}}, f)
        self.assertEqual(self._poll("stop"), [("t", True)])

    def test_no_file_behaves_as_before(self):
        self.assertEqual(self._poll("shutdown"), [("t", False)])


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402
from claudeops import steward as sw  # noqa: E402


class CostWatch(unittest.TestCase):
    def setUp(self):
        ws._COST_WATCH.clear()
        ws._COST_WATCH.update(day="", warned=False, stopped=False)
        self.addCleanup(ws._COST_WATCH.update, day="", warned=False, stopped=False)
        self.sent, self.stops = [], []
        cfg = sw.Config(); cfg.brain_cli = "ucli"
        self.cfg = cfg
        for p in (mock.patch.object(ws, "notify_phone", lambda text, **k: self.sent.append(text) or True),
                  mock.patch.object(ws, "brain_stop", lambda c=None: self.stops.append(1) or {"ok": True}),
                  mock.patch.object(ws, "steward_ids", lambda: []),
                  mock.patch.object(ws.sw, "log_event", lambda *a, **k: None)):
            p.start(); self.addCleanup(p.stop)

    def _state(self, usd, cap=10.0):
        return mock.patch("claudeops.ucli_cost.state", lambda **k: {"today_usd": usd, "cap_usd": cap, "pct": None, "cache_ttl": "1h"})

    def test_no_cap_does_nothing(self):
        with self._state(50, 0):
            ws.ucli_cost_watch(self.cfg)
        self.assertEqual((self.sent, self.stops), ([], []))

    def test_warn_once_at_80(self):
        with self._state(8.5):
            ws.ucli_cost_watch(self.cfg); ws.ucli_cost_watch(self.cfg)
        self.assertEqual((len(self.sent), self.stops), (1, []))

    def test_cap_stops_brain_once(self):
        with self._state(10.2):
            ws.ucli_cost_watch(self.cfg); ws.ucli_cost_watch(self.cfg)
        self.assertEqual((len(self.sent), len(self.stops)), (1, 1))

    def test_claude_brain_not_stopped(self):
        self.cfg.brain_cli = "claude"
        with self._state(11):
            ws.ucli_cost_watch(self.cfg)
        self.assertEqual((len(self.sent), self.stops), (1, []))

    def test_raising_cap_rearms_watch(self):
        with self._state(10.5, 10.0):
            ws.ucli_cost_watch(self.cfg)                      # tavan: durdurur
        self.assertEqual(len(self.stops), 1)
        with self._state(10.5, 20.0):
            ws.ucli_cost_watch(self.cfg)                      # tavan yükseldi, %80 altı: sessiz
        self.assertEqual((len(self.sent), len(self.stops)), (1, 1))
        with self._state(16.5, 20.0):
            ws.ucli_cost_watch(self.cfg)                      # yeni tavanın %80'i: tekrar uyarır
        self.assertEqual(len(self.sent), 2)
        with self._state(20.5, 20.0):
            ws.ucli_cost_watch(self.cfg)                      # yeni tavanda tekrar durdurur
        self.assertEqual(len(self.stops), 2)

    def test_cap_stops_all_ucli_identities(self):
        def cfg_for(sid):
            c = sw.Config(); c.brain_cli = "claude" if sid == "b" else "ucli"
            return c
        with mock.patch.object(ws, "steward_ids", lambda: ["a", "b", "c"]), \
                mock.patch.object(ws, "steward_config", cfg_for), self._state(11):
            ws.ucli_cost_watch(self.cfg)
        self.assertEqual(len(self.stops), 3)              # base + a + c (b claude: dokunulmaz)

    def test_same_cap_does_not_rearm(self):
        with self._state(8.5):
            ws.ucli_cost_watch(self.cfg)
        with self._state(8.6):
            ws.ucli_cost_watch(self.cfg)
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()

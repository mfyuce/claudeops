"""usage_mode: tek (varsayılan, otomatik okuma yok) / tick (oturumsuzlar her tick, oturum isteyenler en fazla 30 dk'da bir)."""
import unittest
from unittest import mock

from claudeops import settings, usage_poll
from claudeops.commands import web, web_steward


class Poll(unittest.TestCase):
    KINDS = {"claude": False, "api": False, "agy": True, "copilot": True}

    def setUp(self):
        usage_poll.reset()
        self.calls = []

    def collect(self, only=None):
        self.calls.append(set(only))
        return {"providers": {n: {"supported": True, "available": True} for n in only}}

    def tick(self, mode, now):
        return usage_poll.tick(mode, self.collect, self.KINDS, now, spawn=lambda fn: fn())

    def test_default_is_tek_and_reads_nothing(self):
        self.assertEqual(settings.DEFAULT_SETTINGS["usage_mode"], "tek")
        self.assertEqual(usage_poll.normalize_mode(""), "tek")
        self.assertEqual(usage_poll.normalize_mode("garip"), "tek")
        self.assertFalse(self.tick("tek", 1000.0))
        self.assertEqual(self.calls, [])

    def test_tick_first_round_reads_all_then_only_sessionless_until_30min(self):
        self.assertTrue(self.tick("tick", 1000.0))
        self.assertEqual(self.calls[-1], {"claude", "api", "agy", "copilot"})
        self.assertTrue(self.tick("tick", 1060.0))
        self.assertEqual(self.calls[-1], {"claude", "api"})            # agy/copilot yeni okunmaz
        self.assertTrue(self.tick("tick", 1000.0 + usage_poll.SESSION_MIN_GAP - 1))
        self.assertEqual(self.calls[-1], {"claude", "api"})
        self.assertTrue(self.tick("tick", 1000.0 + usage_poll.SESSION_MIN_GAP))
        self.assertEqual(self.calls[-1], {"claude", "api", "agy", "copilot"})

    def test_results_cached_for_panel(self):
        self.tick("tick", 1000.0)
        last = usage_poll.last()
        self.assertTrue(last["cached"])
        self.assertEqual(last["at"], 1000.0)
        self.assertIn("agy", last["providers"])

    def test_busy_blocks_overlap_and_collector_error_releases(self):
        started = []
        self.assertTrue(usage_poll.tick("tick", self.collect, self.KINDS, 1.0, spawn=lambda fn: started.append(fn)))
        self.assertFalse(usage_poll.tick("tick", self.collect, self.KINDS, 2.0, spawn=lambda fn: started.append(fn)))   # çalışıyor
        usage_poll.reset()
        boom = mock.Mock(side_effect=RuntimeError("x"))
        self.assertTrue(usage_poll.tick("tick", boom, self.KINDS, 3.0, spawn=lambda fn: fn()))
        self.assertTrue(usage_poll.tick("tick", self.collect, self.KINDS, 4.0, spawn=lambda fn: fn()))    # busy bırakıldı


class Wiring(unittest.TestCase):
    def setUp(self):
        usage_poll.reset()

    def test_kinds_classify_session_vs_sessionless(self):
        k = web._usage_kinds()
        self.assertFalse(k["claude"])        # claude -p /usage
        self.assertFalse(k["api"])
        self.assertTrue(k["agy"])
        self.assertNotIn("codex", k)         # usage_command yok

    def test_usage_all_only_filters(self):
        with mock.patch.object(web, "find_sessions", return_value=[]), mock.patch.object(web, "_usage_fresh", return_value=None), \
             mock.patch("claudeops.api_balance.collect", return_value={"api:X": {"supported": True}}):
            out = web._usage_all(only={"agy"})["providers"]
            self.assertEqual(set(out), {"agy"})
            out = web._usage_all(only={"api"})["providers"]
            self.assertEqual(set(out), {"api:X"})

    def test_steward_usage_tick_respects_mode(self):
        coll = mock.Mock(return_value={"providers": {}})
        web_steward.set_usage_collector(coll, lambda: {"claude": False})
        with mock.patch("claudeops.settings.load_settings", return_value={"usage_mode": "tek"}), \
             mock.patch("claudeops.usage_poll.threading.Thread") as th:
            web_steward.usage_tick(1000.0)
            th.assert_not_called()
        with mock.patch("claudeops.settings.load_settings", return_value={"usage_mode": "tick"}), \
             mock.patch("claudeops.usage_poll.threading.Thread") as th:
            web_steward.usage_tick(1000.0)
            th.assert_called_once()
        web_steward.set_usage_collector(web._usage_all, web._usage_kinds)

    def test_save_validates_mode(self):
        res = web._save_settings({"usage_mode": "hepsi"})
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()

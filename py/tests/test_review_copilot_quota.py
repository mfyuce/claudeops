"""Copilot AI Credits kullanımına dayalı ÖN blok (usage_state): 94 -> blok yok, 95 -> blok; reset parse; koşu-hatası engeli korunur."""
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402

NOW = 1_000_000.0


def entry(pct, detail="1,425 / 1,500 AIC · resets in 8 days"):
    return [{"label": "Plan (AI Credits)", "percent": str(pct), "detail": detail}]


class ParseTests(unittest.TestCase):
    def test_parse_pct_and_relative_reset(self):
        pct, reset, _d = rv.parse_copilot_entries(entry(35, "530 / 1,500 AIC · resets in 8 days"), NOW)
        self.assertEqual((pct, reset), (35.0, NOW + 8 * 86400))

    def test_parse_hours_minutes_and_base_time(self):
        _p, reset, _d = rv.parse_copilot_entries(entry(96, "x · resets in 3 hours 20 minutes"), NOW, base=NOW - 600)
        self.assertEqual(reset, NOW - 600 + 3 * 3600 + 20 * 60)

    def test_unreadable_reset_falls_back_to_24h_and_unrelated_rows_ignored(self):
        _p, reset, _d = rv.parse_copilot_entries(entry(96, "1,440 / 1,500 AIC"), NOW)
        self.assertEqual(reset, NOW + 24 * 3600)
        self.assertIsNone(rv.parse_copilot_entries([{"label": "Chat messages", "percent": "99", "detail": ""}], NOW))
        self.assertIsNone(rv.parse_copilot_entries([], NOW))
        self.assertIsNone(rv.parse_copilot_entries(entry("abc"), NOW))


class ReconcileTests(unittest.TestCase):
    def info(self, pct):
        return rv.parse_copilot_entries(entry(pct), NOW)

    def test_94_no_block_95_blocks_until_reset(self):
        h = {}
        self.assertEqual(rv.reconcile_copilot_blocks(h, self.info(94), 95, NOW), [])
        self.assertEqual(h.get("blocks", {}), {})
        self.assertEqual(rv.reconcile_copilot_blocks(h, self.info(95), 95, NOW), ["copilot"])
        self.assertEqual(h["blocks"]["copilot"]["until"], NOW + 8 * 86400)
        self.assertIn("%95", h["blocks"]["copilot"]["reason"])
        self.assertEqual(rv.blocked_modes(h, NOW + 1), ["copilot"])
        self.assertEqual(rv.reconcile_copilot_blocks(h, self.info(97), 95, NOW + 60), [])      # aynı reset: yeniden yazılmaz

    def test_drop_below_threshold_clears_only_own_block(self):
        h = {}
        rv.reconcile_copilot_blocks(h, self.info(96), 95, NOW)
        self.assertEqual(rv.reconcile_copilot_blocks(h, self.info(10), 95, NOW + 10), ["copilot"])     # yeni ay: kota sıfırlandı
        self.assertNotIn("copilot", h["blocks"])
        h = {"blocks": {"copilot": {"until": NOW + 5000, "reason": "aylık kota doldu", "set_at": NOW}}}   # koşu-hatası engeli
        self.assertEqual(rv.reconcile_copilot_blocks(h, self.info(10), 95, NOW), [])
        self.assertIn("copilot", h["blocks"])

    def test_disabled_or_unknown_does_nothing(self):
        h = {}
        self.assertEqual(rv.reconcile_copilot_blocks(h, self.info(99), 0, NOW), [])
        self.assertEqual(rv.reconcile_copilot_blocks(h, None, 95, NOW), [])
        self.assertEqual(h, {})


class RefreshTests(unittest.TestCase):
    def run_refresh(self, pct, stop=95, mode="copilot"):
        rec = {"available": True, "stale": False, "at": NOW, "entries": entry(pct)}
        hist = {"blocks": {}}
        saved = []
        with mock.patch("claudeops.usage_state.provider", lambda name, now=None, **k: rec if name == "copilot" else None), \
             mock.patch.object(wr.rv, "load_history", lambda p: hist), mock.patch.object(wr.rv, "save_history", lambda p, h: saved.append(1)), \
             mock.patch.object(wr.sw, "steward_lock", mock.MagicMock()), mock.patch.object(wr.sw, "_pp", lambda p: p), \
             mock.patch.object(wr.sw, "log_event", lambda *a, **k: None):
            ch = wr.refresh_copilot_blocks("p", NS(review_copilot_stop_pct=stop), [NS(mode=mode)], NOW)
        return ch, hist

    def test_94_vs_95_via_usage_state_fixture(self):
        ch, h = self.run_refresh(94)
        self.assertEqual((ch, h["blocks"]), ([], {}))
        ch, h = self.run_refresh(95)
        self.assertEqual(ch, ["copilot"])
        self.assertGreater(h["blocks"]["copilot"]["until"], NOW)

    def test_custom_threshold_and_no_copilot_target(self):
        self.assertEqual(self.run_refresh(80, stop=80)[0], ["copilot"])
        self.assertEqual(self.run_refresh(99, mode="agy")[0], [])
        self.assertEqual(self.run_refresh(99, stop=0)[0], [])

    def test_stale_record_ignored(self):
        rec = {"available": True, "stale": True, "at": NOW, "entries": entry(99)}
        with mock.patch("claudeops.usage_state.provider", lambda name, now=None, **k: rec):
            self.assertIsNone(wr.copilot_quota_info(NOW))

    def test_quota_view_shows_pct_and_block_end(self):
        rec = {"available": True, "stale": False, "at": NOW, "entries": entry(96)}
        hist = {"blocks": {"copilot": {"until": NOW + 100, "reason": "x"}}}
        with mock.patch("claudeops.usage_state.provider", lambda name, now=None, **k: rec):
            v = wr._copilot_quota_view(NS(review_copilot_stop_pct=95), hist, NOW)
        self.assertEqual((v["used_pct"], v["stop_pct"], v["blocked_until"]), (96.0, 95, NOW + 100))


if __name__ == "__main__":
    unittest.main()

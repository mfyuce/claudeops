"""codex 'You've hit your usage limit ... try again at <tarih>' = hesap geneli kota bloğu (7 Kas: 24 saatte 12 boş koşu)."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claudeops import review as rv  # noqa: E402

MSG = "exit=1 OR: You’ve hit your usage limit. Upgrade to Plus to continue using Codex (https://chatgpt.com/explore/plus), or try again at Nov 20th, 2026 6:37 PM."


class CodexUsageLimit(unittest.TestCase):
    def test_recognised_as_quota_and_usage_limit(self):
        self.assertTrue(rv.is_quota_exhausted(MSG))
        self.assertTrue(rv.is_usage_limit(MSG))
        self.assertFalse(rv.is_usage_limit("RESOURCE_EXHAUSTED quota reached"))      # agy: model başına, hesap geneli değil

    def test_reset_at_parsed_local_time(self):
        at = rv.reset_at(MSG)
        self.assertEqual(time.strftime("%Y-%m-%d %H:%M", time.localtime(at)), "2026-11-20 18:37")

    def test_block_until_uses_absolute_time_capped(self):
        now = time.mktime(time.strptime("2026-11-07 20:00", "%Y-%m-%d %H:%M"))
        self.assertEqual(rv.quota_block_until(now, MSG), rv.reset_at(MSG))
        far = "try again at Dec 31st, 2026 6:37 PM"
        self.assertEqual(rv.quota_block_until(now, far), now + rv.QUOTA_MAX_SECONDS)

    def test_past_or_unparsable_falls_back(self):
        now = time.mktime(time.strptime("2026-12-01 00:00", "%Y-%m-%d %H:%M"))
        self.assertEqual(rv.quota_block_until(now, MSG), now + rv.QUOTA_FALLBACK_SECONDS)
        self.assertEqual(rv.quota_block_until(1000.0, "hit your usage limit"), 1000.0 + rv.QUOTA_FALLBACK_SECONDS)

    def test_existing_agy_reset_in_still_works(self):
        self.assertEqual(rv.quota_block_until(1000.0, "Resets in 1h"), 1000.0 + 3600)


if __name__ == "__main__":
    unittest.main()

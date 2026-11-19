"""copilot oturumsuz kullanım (TUI yolu): ayrıştırma (canlı ekran fikstürü) + TTL önbelleği. Gerçek tmux/copilot YOK."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.commands import web  # noqa: E402
from claudeops.providers.copilot_provider import CopilotProvider  # noqa: E402

SCREEN = """   Active account/provider usage
   Plan       ■■■■■■■■■■■■■■■■■■■■ 35% used • resets in 11 days
              530 / 1,500 AIC
 /tmp
"""


class P(unittest.TestCase):
    def test_parse_percent_fraction_reset(self):
        e = CopilotProvider().parse_fresh_usage(SCREEN)
        self.assertEqual(e, [{"label": "Plan (AI Credits)", "percent": "35", "detail": "530 / 1,500 AIC · resets in 11 days"}])

    def test_parse_without_reset_unchanged(self):
        e = CopilotProvider().parse_usage_text("Plan   ■■ 10% used\n 5 / 100 AIC\n")
        self.assertEqual(e[0]["detail"], "5 / 100 AIC")

    def test_argv_and_no_print_mode(self):
        a = CopilotProvider().usage_fresh_tui_argv()
        self.assertEqual(len(a), 1)
        self.assertNotIn("-p", a)


class Ttl(unittest.TestCase):
    def setUp(self):
        web._USAGE_TUI_CACHE.clear()
        self.p = CopilotProvider()

    def test_ttl_cache_and_stale(self):
        ok = {"available": True, "entries": [1]}
        with mock.patch.object(web, "_usage_fresh_tui_run", side_effect=[ok, None, None]) as m:
            self.assertEqual(web._usage_fresh_tui(self.p, now=1000.0), ok)
            self.assertEqual(web._usage_fresh_tui(self.p, now=1100.0), ok)      # vade dolmadı: yeniden okunmaz
            self.assertEqual(m.call_count, 1)
            r = web._usage_fresh_tui(self.p, now=1000.0 + web._USAGE_TUI_TTL + 1)   # başarısız: son iyi değer, işaretli
            self.assertTrue(r["stale_read"])
            self.assertIsNone(web._usage_fresh_tui(self.p, now=1000.0 + 3 * web._USAGE_TUI_TTL))


if __name__ == "__main__":
    unittest.main()

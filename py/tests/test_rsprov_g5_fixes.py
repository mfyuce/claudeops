"""rs/prov G5/G11 (kota/bağlam ayrıştırıcıları, ucli ölçüm ayarı) Python hataları: iki tarafta düzeldi
(Rust `cops-providers` `usage.rs`, `settings.rs`).

Çalıştırma:  python3 -m unittest discover -s py/tests -p test_rsprov_g5_fixes.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings, ucli_metrics  # noqa: E402
from claudeops.providers import agy_provider as ap  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402
from claudeops.providers import copilot_provider as cop  # noqa: E402


class MetricsTest(unittest.TestCase):
    def test_nan_falls_back_to_the_default(self):
        c = ucli_metrics.get_config({"interval_s": "nan", "retention_days": "NaN"})
        d = ucli_metrics.get_config({})
        self.assertEqual((c["interval_s"], c["retention_days"]), (d["interval_s"], d["retention_days"]))


class ServicesTest(unittest.TestCase):
    def test_numeric_models_field_does_not_drop_the_list(self):     # main'de düzelmişti (TBD#374 S8): korunuyor
        out = settings.normalize_ucli_services([{"id": "m1", "env": "M1_KEY", "endpoint": "https://m", "models": 5},
                                                {"id": "m2", "env": "M2_KEY", "endpoint": "https://m", "models": True}])
        self.assertEqual([(s["id"], s["models"]) for s in out if s["id"] != "evren"], [("m1", []), ("m2", [])])


class CopilotTest(unittest.TestCase):
    def parse(self, text):
        return cop.CopilotProvider().parse_usage_text(text)

    def test_bar_glued_to_the_percent(self):
        self.assertEqual(self.parse("Plan ■■50% used")[0]["percent"], "50")
        self.assertEqual(self.parse("Plan 2025 50% used")[0]["percent"], "50")
        self.assertEqual(self.parse("Plan ■■■■ 7% used")[0]["percent"], "7")

    def test_blank_reset_is_not_shown(self):
        self.assertEqual(self.parse("Plan 5% used resets in   ")[0]["detail"], "")
        self.assertEqual(self.parse("Plan 5% used resets in 11 days")[0]["detail"], "resets in 11 days")

    def test_only_ascii_digits(self):
        self.assertIsNone(self.parse("Plan ٥٠% used"))


class ClaudeTest(unittest.TestCase):
    def test_bare_resets_word_is_not_the_detail(self):
        e = cp.ClaudeProvider().parse_fresh_usage("Current session: 5% used · resets")
        self.assertEqual(e, [{"label": "Current session", "percent": "5", "detail": ""}])
        e = cp.ClaudeProvider().parse_fresh_usage("Current session: 5% used · resets 3pm")
        self.assertEqual(e[0]["detail"], "Resets 3pm")

    def test_non_ascii_category_name_is_not_cut(self):
        p = cp.ClaudeProvider()
        self.assertIsNone(p.parse_context_text("Şey: 1k tokens (1%)"))
        self.assertEqual(p.parse_context_text("⛁ Messages: 1k tokens (1%)")[0]["label"], "Messages")

    def test_only_ascii_digits(self):
        self.assertIsNone(cp.ClaudeProvider().parse_fresh_usage("Current session: ٣% used"))


class AgyTest(unittest.TestCase):
    def test_superscript_and_circled_digits_are_not_percent(self):
        p = ap.AgyProvider()
        for pct in ("²%", "①%", "٣%"):
            with self.subTest(pct=pct):
                self.assertIsNone(p.parse_usage_text(f"G\tWeekly\t{pct}\t2026-11-30T00:00:00Z"))
        self.assertEqual(p.parse_usage_text("G\tWeekly\t42%\tT")[0]["percent"], "42")


if __name__ == "__main__":
    unittest.main()

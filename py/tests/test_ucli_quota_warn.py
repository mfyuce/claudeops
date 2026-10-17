"""ucli token rozeti: Evren KOTA EŞDEĞERİ ve renk eşikleri (stdlib unittest).

Çalıştırma:  python3 py/tests/test_ucli_quota_warn.py -v

Kapsadığı iş (TODO.md 2026-10-16 (5) madde 1 kalanı, kullanıcı "Token rozetine eşik"i seçti): rozet ham toplamı
(girdi + çıktı, önbellekli dahil) gösteriyordu; Evren hesap kotasında önbellekli girdiyi %3 sayıyor (unified-cli
bench/token-economy: koşu A'da pano 12,8M, kota 0,93M), yani "10 dakikada 10 milyon" ham sayısı kotayı yansıtmaz.
Satıra `quota_tokens` (kota eşdeğeri) ve `warn` (0 yok / 1 amber / 2 kırmızı) eklenir; eşikler Ayarlar'daki
`ucli_usage_warn` (varsayılan 1M / 3M, `off` = kademe kapalı). YALNIZ renk: durdurma YOK. Gerçek settings.json'a,
filoya, ağa ya da tmux'a DOKUNMAZ.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import settings  # noqa: E402
from claudeops import ucli_client as uc  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.session import Session  # noqa: E402


class QuotaEquivalentTests(unittest.TestCase):
    def test_a_real_session_prompt_cache_counts_three_percent(self):
        """wifi5gppr20261016_4 (gerçek durum dosyası, 12 istek): 197.625 önbelleksiz + 251.648 x 0,03 + 17.105 çıktı."""
        u = {"prompt_tokens": 449_273, "cached_tokens": 251_648, "completion_tokens": 17_105}
        self.assertEqual(uc.quota_equivalent_tokens(u), 222_279)

    def test_the_weight_is_the_measured_three_percent(self):
        self.assertEqual(uc.QUOTA_CACHED_WEIGHT, 0.03)

    def test_uncached_input_and_output_count_in_full(self):
        self.assertEqual(uc.quota_equivalent_tokens({"prompt_tokens": 1000, "cached_tokens": 0, "completion_tokens": 50}), 1050)

    def test_a_fully_cached_prompt_costs_three_percent(self):
        self.assertEqual(uc.quota_equivalent_tokens({"prompt_tokens": 100_000, "cached_tokens": 100_000, "completion_tokens": 0}), 3000)

    def test_cached_cannot_exceed_the_prompt(self):
        """Bozuk bir dosya (cached > prompt) girdiyi aşıp negatif önbelleksiz girdi üretmesin."""
        self.assertEqual(uc.quota_equivalent_tokens({"prompt_tokens": 1000, "cached_tokens": 9_999_999, "completion_tokens": 0}), 30)

    def test_missing_and_negative_values_are_clamped_to_zero(self):
        self.assertEqual(uc.quota_equivalent_tokens({}), 0)
        self.assertEqual(uc.quota_equivalent_tokens({"prompt_tokens": -5, "cached_tokens": -1, "completion_tokens": -7}), 0)

    def test_reasoning_tokens_are_not_added_again(self):
        """`reasoning_tokens` `completion_tokens`ın alt kümesi: ikinci kez sayılırsa kota şişer."""
        base = {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 500}
        self.assertEqual(uc.quota_equivalent_tokens({**base, "reasoning_tokens": 400}), 500)


class WarnLevelTests(unittest.TestCase):
    def test_levels_follow_the_thresholds_and_boundaries_are_inclusive(self):
        table = [(0, 0), (999, 0), (1000, 1), (4999, 1), (5000, 2), (10**9, 2)]
        for quota, level in table:
            with self.subTest(quota=quota):
                self.assertEqual(uc.usage_warn_level(quota, 1000, 5000), level)

    def test_a_zero_threshold_switches_that_level_off(self):
        self.assertEqual(uc.usage_warn_level(10**9, 0, 0), 0)
        self.assertEqual(uc.usage_warn_level(2000, 1000, 0), 1)       # kırmızı kapalı, amber açık
        self.assertEqual(uc.usage_warn_level(2000, 0, 1500), 2)       # amber kapalı, kırmızı açık

    def test_a_red_below_amber_typo_still_gives_the_heaviest_level(self):
        self.assertEqual(uc.usage_warn_level(2000, 5000, 1000), 2)


class ThresholdSettingTests(unittest.TestCase):
    def thresholds(self, raw):
        with mock.patch.object(settings, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, "ucli_usage_warn": raw}):
            return settings.ucli_usage_warn_thresholds()

    def test_unset_means_one_million_and_three_million(self):
        self.assertEqual(settings.USAGE_WARN_DEFAULTS, {"amber": 1_000_000, "red": 3_000_000})
        self.assertEqual(self.thresholds({}), (1_000_000, 3_000_000))

    def test_custom_values_win_as_strings_or_numbers_with_separators(self):
        self.assertEqual(self.thresholds({"amber": "500000", "red": 2_000_000}), (500_000, 2_000_000))
        self.assertEqual(self.thresholds({"amber": "1_500_000", "red": "2,500,000"}), (1_500_000, 2_500_000))

    def test_off_words_and_zero_disable_a_level(self):
        self.assertEqual(self.thresholds({"amber": "off", "red": "0"}), (0, 0))
        self.assertEqual(self.thresholds({"red": "OFF"}), (1_000_000, 0))

    def test_garbage_falls_back_to_the_default_of_that_level(self):
        for bad in ("abc", "-5", "1.5", " ", None, [], {}):
            with self.subTest(value=bad):
                self.assertEqual(self.thresholds({"amber": bad}), (1_000_000, 3_000_000))

    def test_a_non_dict_setting_is_tolerated(self):
        self.assertEqual(self.thresholds(["x"]), (1_000_000, 3_000_000))

    def test_the_setting_is_part_of_the_schema_and_merges_per_field(self):
        self.assertIn("ucli_usage_warn", settings.DEFAULT_SETTINGS)
        stored = {}
        with mock.patch.object(settings, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, "ucli_usage_warn": dict(stored)}), \
                mock.patch.object(settings, "atomic_write_json", lambda path, data, **kw: stored.update(data["ucli_usage_warn"])
                                  if isinstance(data.get("ucli_usage_warn"), dict) else None):
            settings.save_settings({"ucli_usage_warn": {"amber": "750000"}})
        self.assertEqual(stored, {"amber": "750000"})


class LiveUsageWarnTests(unittest.TestCase):
    def session(self):
        return Session(name="u1", pid=1, cwd="/w/proj", sid="u1", cli="ucli")

    def usage(self, prompt, cached, completion, **extra):
        return {"requests": 3, "reported": 3, "prompt_tokens": prompt, "cached_tokens": cached,
                "completion_tokens": completion, "reasoning_tokens": 0, "request_bytes": 10,
                "unmetered": 0, "unmetered_bytes": 0, **extra}

    def live(self, usage, thresholds=(1000, 5000)):
        fake = mock.Mock()
        fake.live_usage.return_value = usage
        with mock.patch.object(web, "get_provider", return_value=fake), \
                mock.patch.object(web, "ucli_usage_warn_thresholds", lambda: thresholds):
            return web._live_usage(self.session())

    def test_the_row_gets_the_quota_equivalent_and_the_level(self):
        for usage, level in ((self.usage(500, 0, 100), 0), (self.usage(900, 0, 200), 1), (self.usage(5000, 0, 500), 2)):
            with self.subTest(prompt=usage["prompt_tokens"]):
                got = self.live(usage)
                self.assertEqual(got["quota_tokens"], usage["prompt_tokens"] + usage["completion_tokens"])
                self.assertEqual(got["warn"], level)

    def test_cached_input_does_not_trip_the_warning_the_way_the_raw_total_would(self):
        """Ham toplam 100.600 (amber eşiğinin 20 katı) ama %99'u önbellekli: kota eşdeğeri 1.000 + 2.970 + 600 = 4.570, eşiğin (5.000) altında, uyarı YOK."""
        got = self.live(self.usage(100_000, 99_000, 600), thresholds=(5000, 50_000))
        self.assertEqual((got["quota_tokens"], got["warn"]), (1000 + 2970 + 600, 0))

    def test_the_providers_own_dict_is_not_mutated(self):
        original = self.usage(900, 0, 200)
        snapshot = dict(original)
        self.live(original)
        self.assertEqual(original, snapshot)

    def test_a_counter_without_token_fields_passes_through_unchanged(self):
        self.assertEqual(self.live({"requests": 1}), {"requests": 1})
        self.assertIsNone(self.live(None))

    def test_a_broken_threshold_setting_never_breaks_the_row(self):
        fake = mock.Mock()
        fake.live_usage.return_value = self.usage(900, 0, 200)
        with mock.patch.object(web, "get_provider", return_value=fake), \
                mock.patch.object(web, "ucli_usage_warn_thresholds", side_effect=RuntimeError("boom")):
            got = web._live_usage(self.session())
        self.assertEqual(got, self.usage(900, 0, 200))


if __name__ == "__main__":
    unittest.main()

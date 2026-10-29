"""Çoklu değnekçi P2: `stewards.*` ayarı, kimlik kuralı, beyin adı türetme, iki seviye `save_settings`,
default `Config`'in birebir korunması. `settings.SETTINGS_JSON` geçici dosyaya yönlendirilir."""
import dataclasses
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import settings, steward as sw  # noqa: E402

# P2 öncesi `steward_config()` çıktısı (boş ayar): ALTIN. Yeni alanlar ayrı sınanır.
GOLDEN_DEFAULT = {
    "enabled": False, "tick_seconds": 120, "tour_minutes": 15, "tour_retry_minutes": 5, "max_active": 4, "max_starts_per_tick": 1,
    "idle_minutes": 10, "review_minutes": 90, "stop_idle_minutes": 45, "ho_grace_minutes": 15,
    "history_warn_at": 1900, "history_min_age_minutes": 15, "context_warn_tokens_fable": 150000,
    "context_warn_tokens": 300000, "brain_cli": "claude", "brain_model": "", "brain_effort": "high",
    "brain_name": "degnekci", "planning_model": "", "planning_effort": "medium", "planned_model": "",
    "planned_effort": "", "lang": "tr", "card_refresh": True, "card_cli": "claude", "card_model": "",
    "card_max_age_hours": 24, "cards_per_tick": 1, "mode": "observe", "summary_hour": 21, "resume_max_context_tokens": 150000, "keepwarm": "dry", "keepwarm_after_minutes": 52, "keepwarm_min_tokens": 100000, "keepwarm_max_consecutive": 2, "wake_gate": "dry", "wake_max_per_day": 2, "wake_repeat_minutes": 240,
}
NEW_FIELDS = {"sid", "label", "persona_text", "ntfy_topic", "max_active_total", "max_starts_total", "remote_actions",
              "auto_context_answer", "auto_context_ratio", "drain", "role", "review_timeout_minutes",
              "review_min_gap_minutes", "review_agy_models", "review_evren_models", "review_claude_models", "review_codex_models", "review_codex_effort", "review_claude_effort", "review_max_context_kib", "review_max_compactions", "review_max_tool_calls", "review_evren_script", "review_agy_allow", "review_agy_jail", "review_copilot_models", "review_copilot_effort", "review_evren_effort",
              "handover_force_ratio", "handover_defer_max_minutes", "lessons_project", "advance_findings", "review_auto_verify", "review_verify_mode", "review_auto_approve", "review_before_tbd_dir", "review_store_dir", "review_store_commit", "review_store_git_dir", "review_auto_export", "review_max_wall_secs", "review_max_output_tokens", "review_request_timeout_secs", "upper_main_warn"}


def _write(obj):
    with open(settings.SETTINGS_JSON, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _old_part(cfg):
    return {k: v for k, v in dataclasses.asdict(cfg).items() if k not in NEW_FIELDS}


class TestIds(unittest.TestCase):
    def test_valid(self):
        for ok in ("default", "kitap", "ab", "abcdefghijklmnop"):
            self.assertTrue(sw.valid_steward_id(ok), ok)
        for bad in ("", "a", "abcdefghijklmnopq", "Kitap", "kitap2", "ki_tap", "ki-tap", "all", "services",
                    "degnekci", "degnekcix", None, 5):
            self.assertFalse(sw.valid_steward_id(bad), repr(bad))
        self.assertFalse(sw.valid_custom_id("default"))

    def test_brain_name(self):
        self.assertEqual(sw.brain_name_for("default"), "degnekci")
        self.assertEqual(sw.brain_name_for("kitap"), "degnekci_kitap")


class TestStewardSettings(_Tmp):
    def test_golden_default_empty(self):
        cfg = settings.steward_config()
        self.assertEqual(_old_part(cfg), GOLDEN_DEFAULT)
        self.assertEqual((cfg.sid, cfg.max_active_total, cfg.max_starts_total), ("default", 6, 1))
        self.assertEqual(dataclasses.asdict(settings.steward_config("default")), dataclasses.asdict(cfg))

    def test_handover_defer_fields(self):
        cfg = settings.steward_config()
        self.assertEqual((cfg.handover_force_ratio, cfg.handover_defer_max_minutes), (1.3, 30))
        _write({"steward": {"handover_force_ratio": "1.5", "handover_defer_max_minutes": "10", "auto_context_ratio": "0.6"}})
        cfg = settings.steward_config()
        self.assertEqual((cfg.handover_force_ratio, cfg.handover_defer_max_minutes, cfg.auto_context_ratio), (1.5, 10, 0.6))
        _write({"steward": {"handover_force_ratio": "x"}})
        self.assertEqual(settings.steward_config().handover_force_ratio, 1.3)

    def test_default_ignores_stewards_block(self):
        _write({"steward": {"enabled": "on", "mode": "act", "max_active": "3"},
                "stewards": {"kitap": {"enabled": "on", "max_active": "9", "mode": "act"}}})
        cfg = settings.steward_config()
        self.assertTrue(cfg.enabled)
        self.assertEqual((cfg.mode, cfg.max_active, cfg.brain_name), ("act", 3, "degnekci"))

    def test_default_brain_name_override_kept(self):
        _write({"steward": {"brain_name": "benimbeyin"}})
        self.assertEqual(settings.steward_config().brain_name, "benimbeyin")

    def test_ids(self):
        self.assertEqual(settings.steward_ids(), ["default"])
        _write({"stewards": {"zeta": {}, "kitap": {"enabled": "on"}, "Bad": {}, "degnekci": {}, "all": {},
                             "default": {}, "x": {}, "str": "bozuk"}})
        self.assertEqual(settings.steward_ids(), ["default", "kitap", "zeta"])

    def test_custom_cfg(self):
        _write({"steward": {"enabled": "on", "mode": "act", "max_active": "4", "tick_seconds": "90",
                            "cards_per_tick": "2", "max_active_total": "8", "max_starts_total": "2",
                            "brain_effort": "low", "lang": "en", "brain_name": "zzz"},
                "stewards": {"kitap": {"label": "Kitaplar", "enabled": "on", "mode": "observe", "max_active": "2",
                                       "brain_model": "m", "summary_hour": "9", "persona_text": "p", "ntfy_topic": "t",
                                       "tick_seconds": "999", "max_active_total": "77", "brain_name": "hile", "sid": "baska"}}})
        cfg = settings.steward_config("kitap")
        self.assertEqual((cfg.sid, cfg.label, cfg.enabled, cfg.mode, cfg.max_active), ("kitap", "Kitaplar", True, "observe", 2))
        self.assertEqual((cfg.brain_model, cfg.summary_hour, cfg.persona_text, cfg.ntfy_topic), ("m", 9, "p", "t"))
        # kimlik başına anahtarlar `steward` bloğundan MİRAS ALINMAZ (Config varsayılanı)
        self.assertEqual((cfg.brain_effort, cfg.lang), ("high", "tr"))
        # makine geneli yalnız `steward`'tan; kimlik bloğundakiler yok sayılır
        self.assertEqual((cfg.tick_seconds, cfg.cards_per_tick, cfg.max_active_total, cfg.max_starts_total), (90, 2, 8, 2))
        self.assertEqual(cfg.brain_name, "degnekci_kitap")

    def test_unknown_and_invalid_sid(self):
        cfg = settings.steward_config("yeni")      # blok yok: Config varsayılanları, kapalı
        self.assertEqual((cfg.sid, cfg.enabled, cfg.brain_name), ("yeni", False, "degnekci_yeni"))
        for bad in ("Kitap", "all", "degnekci", ""):
            with self.assertRaises(ValueError):
                settings.steward_config(bad)

    def test_custom_bad_values_tolerated(self):
        _write({"stewards": {"kitap": {"max_active": "abc", "mode": "bogus", "summary_hour": "40", "lang": "xx"}}})
        cfg = settings.steward_config("kitap")
        self.assertEqual((cfg.max_active, cfg.mode, cfg.summary_hour, cfg.lang), (4, "observe", 23, "tr"))
        _write({"stewards": "bozuk"})
        self.assertEqual(settings.steward_ids(), ["default"])
        self.assertEqual(settings.steward_config("kitap").sid, "kitap")


class TestSaveTwoLevel(_Tmp):
    def _stewards(self):
        return settings.load_settings()["stewards"]

    def test_partial_update_keeps_other_ids(self):
        settings.save_settings({"stewards": {"kitap": {"label": "K", "mode": "act", "max_active": 2},
                                             "oyun": {"label": "O", "enabled": "on"}}})
        settings.save_settings({"stewards": {"kitap": {"mode": "observe"}}})
        st = self._stewards()
        self.assertEqual(st["kitap"], {"label": "K", "mode": "observe", "max_active": "2"})
        self.assertEqual(st["oyun"], {"label": "O", "enabled": "on"})
        # diskteki dosyada da
        with open(settings.SETTINGS_JSON, encoding="utf-8") as f:
            self.assertEqual(sorted(json.load(f)["stewards"]), ["kitap", "oyun"])

    def test_empty_removes_field_none_removes_id(self):
        settings.save_settings({"stewards": {"kitap": {"label": "K", "mode": "act"}, "oyun": {"label": "O"}}})
        settings.save_settings({"stewards": {"kitap": {"label": ""}}})
        self.assertEqual(self._stewards()["kitap"], {"mode": "act"})
        settings.save_settings({"stewards": {"oyun": None}})
        self.assertEqual(sorted(self._stewards()), ["kitap"])
        settings.save_settings({"stewards": {"nope": None}})     # olmayanı silmek zararsız
        self.assertEqual(sorted(self._stewards()), ["kitap"])

    def test_invalid_ids_skipped_and_other_keys_untouched(self):
        settings.save_settings({"steward": {"enabled": "on"}, "stewards": {"kitap": {"label": "K"}}})
        settings.save_settings({"stewards": {"default": {"mode": "act"}, "Bad": {"a": "b"}, "degnekci": {"a": "b"},
                                             "all": {"a": "b"}, "oyun": "str"}})
        self.assertEqual(sorted(self._stewards()), ["kitap"])
        self.assertEqual(settings.load_settings()["steward"], {"enabled": "on"})
        settings.save_settings({"stewards": {"kitap": {"label": "K2"}}})
        self.assertEqual(settings.load_settings()["steward"], {"enabled": "on"})

    def test_bool_and_steward_block_unaffected(self):
        settings.save_settings({"stewards": {"kitap": {"enabled": True}}})
        self.assertEqual(self._stewards()["kitap"], {"enabled": "on"})
        self.assertTrue(settings.steward_config("kitap").enabled)
        settings.save_settings({"stewards": {"kitap": {"enabled": False}}})
        self.assertFalse(settings.steward_config("kitap").enabled)

    def test_non_dict_stored_recovers(self):
        _write({"stewards": ["bozuk"]})
        settings.save_settings({"stewards": {"kitap": {"label": "K"}}})
        self.assertEqual(self._stewards(), {"kitap": {"label": "K"}})


if __name__ == "__main__":
    unittest.main()

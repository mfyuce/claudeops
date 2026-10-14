"""Model bazlı effort testleri (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_effort_by_model.py -v

Kapsadığı iş (kullanıcı kararı 2026-10-14: "effort'ları toplayıp modele göre ayarlayalım;
hangisi olursa onu gönderelim, yoksa uygununu set edelim"): panelin varsayılan effort'u
`max`, agy ise seviyeyi model kimliğine gömüyor (`gemini-3.1-pro-high`); ikisi çatışınca agy
modeli SESSİZCE kendi varsayılanına düşürüyordu (TODO.md 2026-10-09; canlı filoda 13 kayıt).
Düzeltme: `CliProvider.resolve_effort()`; agy kimliğin kademesini, codex kendi önbelleğini
kullanır, diğerleri BİREBİR aynen geçirir. Gerçek session'lara / dosyalara DOKUNMAZ
(agy listesi `_cache_models` ile, codex önbelleği geçici dosyayla taklit edilir).
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import effort as effort_mod  # noqa: E402
from claudeops import spawn  # noqa: E402
from claudeops.providers import PROVIDERS  # noqa: E402
from claudeops.providers import codex_provider  # noqa: E402
from claudeops.providers.agy_provider import AgyProvider  # noqa: E402

FLASH = ["gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low"]
PRO_PLAN_LIST = FLASH + [
    "claude-opus-5-5-low", "claude-opus-5-5-medium", "claude-opus-5-5-high",
    "claude-sonnet-5-5-low", "claude-sonnet-5-5-medium", "claude-sonnet-5-5-high",
    "gpt-oss-120b-medium",
]


def agy_with_list(models):
    """`agy models` subprocess'ine HİÇ gitmeyen bir AgyProvider (TTL dolmamış cache)."""
    p = AgyProvider()
    p._cache_models = list(models)
    p._cache_ts = time.monotonic()
    return p


def effort_arg(cmd):
    """`... --effort X ...` içindeki X (yoksa None)."""
    toks = cmd.split()
    return toks[toks.index("--effort") + 1] if "--effort" in toks else None


def build(p, model, effort):
    return p.build_inner_command("/tmp", model, "auto", effort, None, None, "t")


class SplitTierTests(unittest.TestCase):
    def test_tiered_ids(self):
        self.assertEqual(effort_mod.split_tier("gemini-3.8-flash-high"), ("gemini-3.8-flash", "high"))
        self.assertEqual(effort_mod.split_tier("gpt-oss-120b-medium"), ("gpt-oss-120b", "medium"))
        self.assertEqual(effort_mod.split_tier("claude-opus-5-5-low"), ("claude-opus-5-5", "low"))
        self.assertEqual(effort_mod.split_tier("gemini-4-argon-xhigh"), ("gemini-4-argon", "xhigh"))

    def test_untiered_ids_are_untouched(self):
        for mid in ("claude-sonnet-5-5", "claude-opus-4-6-thinking", "gemini-4-argon", "gemini-ultra", "high", "-high", ""):
            self.assertEqual(effort_mod.split_tier(mid), (mid, None), mid)

    def test_non_string(self):
        self.assertEqual(effort_mod.split_tier(None), ("", None))


class SortAndNearestTests(unittest.TestCase):
    def test_sort_levels_orders_dedupes_keeps_unknown_last(self):
        self.assertEqual(effort_mod.sort_levels(["high", "low", "weird", "low", "max"]),
                         ["low", "high", "max", "weird"])

    def test_requested_in_levels_is_returned_as_is(self):
        self.assertEqual(effort_mod.nearest_effort("medium", ["low", "medium", "high"]), "medium")

    def test_too_high_goes_to_the_top_supported(self):
        self.assertEqual(effort_mod.nearest_effort("max", ["low", "medium", "high"]), "high")

    def test_prefers_below_over_equally_near_above(self):
        # xhigh istendi; high (1 aşağı) ve max (1 yukarı) eşit uzak: maliyeti artırmamak için high
        self.assertEqual(effort_mod.nearest_effort("xhigh", ["high", "max"]), "high")

    def test_nothing_below_takes_lowest_above(self):
        self.assertEqual(effort_mod.nearest_effort("low", ["medium", "high"]), "medium")

    def test_empty_request_uses_default(self):
        self.assertEqual(effort_mod.nearest_effort(None, ["low", "medium", "high"]), "medium")
        self.assertEqual(effort_mod.nearest_effort("", ["high"]), "high")

    def test_unknown_request_falls_back_via_default_rank(self):
        self.assertEqual(effort_mod.nearest_effort("bogus", ["low", "high"]), "low")

    def test_empty_levels(self):
        self.assertIsNone(effort_mod.nearest_effort("high", []))

    def test_all_unknown_level_names(self):
        self.assertEqual(effort_mod.nearest_effort("high", ["zeta", "alpha"]), "zeta")


class AgyEffortTests(unittest.TestCase):
    def test_tier_in_id_fixes_the_levels(self):
        p = agy_with_list(PRO_PLAN_LIST)
        self.assertEqual(p.model_effort_levels("gemini-3.1-pro-high"), ["high"])
        self.assertEqual(p.model_effort_levels("gpt-oss-120b-medium"), ["medium"])
        self.assertEqual(p.effort_levels_for("gemini-3.8-flash-low"), ["low"])

    def test_untiered_non_gemini_has_no_info(self):
        p = agy_with_list(PRO_PLAN_LIST)
        self.assertIsNone(p.model_effort_levels("claude-opus-4-6-thinking"))
        self.assertEqual(p.effort_levels_for("claude-opus-4-6-thinking"), p.effort_levels())

    def test_base_name_uses_live_siblings(self):
        p = agy_with_list(PRO_PLAN_LIST)
        self.assertEqual(p.model_effort_levels("gemini-3.8-flash"), ["low", "medium", "high"])

    def test_base_name_without_siblings_is_unknown(self):
        p = agy_with_list(PRO_PLAN_LIST)
        self.assertIsNone(p.model_effort_levels("gemini-4-argon"))

    def test_empty_model(self):
        p = agy_with_list(PRO_PLAN_LIST)
        self.assertIsNone(p.model_effort_levels(""))
        self.assertIsNone(p.model_effort_levels(None))

    def test_panel_default_max_no_longer_conflicts_with_tiered_id(self):
        # 2026-10-09 olayı: `--model gemini-3.1-pro-high --effort max` -> agy modeli sessizce düşürüyordu
        p = agy_with_list(PRO_PLAN_LIST)
        cmd = build(p, "gemini-3.1-pro-high", "max")
        self.assertIn("--model gemini-3.1-pro-high", cmd)
        self.assertEqual(effort_arg(cmd), "high")

    def test_empty_effort_no_longer_defaults_to_medium_against_a_high_id(self):
        # eski kod: `effort or "medium"` -> `-high` kimlikle `--effort medium` çatışması
        p = agy_with_list(PRO_PLAN_LIST)
        self.assertEqual(effort_arg(build(p, "gemini-3.8-flash-high", "")), "high")
        self.assertEqual(effort_arg(build(p, "gemini-3.8-flash-high", None)), "high")

    def test_requested_effort_follows_the_id_not_the_other_way(self):
        p = agy_with_list(PRO_PLAN_LIST)
        self.assertEqual(effort_arg(build(p, "gemini-3.8-flash-medium", "high")), "medium")
        self.assertEqual(effort_arg(build(p, "gemini-3.8-flash-low", "max")), "low")

    def test_matching_effort_is_unchanged(self):
        # canlı filodaki bilinen-çalışan biçim: `gemini-3.8-flash-high --effort high`
        p = agy_with_list(PRO_PLAN_LIST)
        self.assertEqual(effort_arg(build(p, "gemini-3.8-flash-high", "high")), "high")
        self.assertEqual(effort_arg(build(p, "gemini-3.1-pro-high", "high")), "high")

    def test_non_gemini_still_gets_no_effort_flag(self):
        # 2026-09-28 kuralı korunuyor: gemini dışında --effort HİÇ gönderilmez
        p = agy_with_list(PRO_PLAN_LIST)
        for mid in ("claude-opus-5-5-high", "claude-sonnet-5-5-medium", "gpt-oss-120b-medium",
                    "claude-opus-4-6-thinking"):
            self.assertIsNone(effort_arg(build(p, mid, "max")), mid)
            self.assertIsNone(effort_arg(build(p, mid, "")), mid)

    def test_argon_ids_are_consistent_with_their_tier(self):
        # Argon'un gerçek engeli buydu (varsayılan medium + -high/-low kimlik = çatışma)
        p = agy_with_list(PRO_PLAN_LIST + ["gemini-4-argon-low", "gemini-4-argon-medium", "gemini-4-argon-high"])
        self.assertEqual(effort_arg(build(p, "gemini-4-argon-high", "medium")), "high")
        self.assertEqual(effort_arg(build(p, "gemini-4-argon-low", "medium")), "low")
        self.assertEqual(effort_arg(build(p, "gemini-4-argon-medium", None)), "medium")

    def test_gemini_base_name_clamps_to_live_tiers(self):
        p = agy_with_list(PRO_PLAN_LIST)
        self.assertEqual(effort_arg(build(p, "gemini-3.8-flash", "max")), "high")
        self.assertEqual(effort_arg(build(p, "gemini-3.8-flash", "low")), "low")

    def test_gemini_base_name_without_info_keeps_old_behaviour(self):
        p = agy_with_list(PRO_PLAN_LIST)  # `gemini-4-argon` kardeşi yok
        self.assertEqual(effort_arg(build(p, "gemini-4-argon", "max")), "max")
        self.assertEqual(effort_arg(build(p, "gemini-4-argon", "")), "medium")


class CodexEffortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = os.path.join(self.tmp.name, "models_cache.json")
        levels = lambda *names: [{"effort": n, "description": "x"} for n in names]  # noqa: E731
        with open(self.cache, "w", encoding="utf-8") as f:
            json.dump({"models": [
                {"slug": "gpt-5.5", "visibility": "hide", "supported_reasoning_levels": levels("low", "medium", "high", "xhigh")},
                {"slug": "gpt-5.6-luna", "visibility": "list", "supported_reasoning_levels": levels("low", "medium", "high", "xhigh", "max")},
                {"slug": "gpt-5.6-terra", "visibility": "list", "supported_reasoning_levels": levels("low", "medium", "high", "xhigh", "max", "ultra")},
                {"slug": "no-levels", "visibility": "list", "supported_reasoning_levels": []},
            ]}, f)
        patcher = mock.patch.object(codex_provider, "MODELS_CACHE", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.p = PROVIDERS["codex"]

    def test_reads_per_model_levels(self):
        self.assertEqual(self.p.model_effort_levels("gpt-5.5"), ["low", "medium", "high", "xhigh"])
        self.assertEqual(self.p.model_effort_levels("gpt-5.6-terra")[-2:], ["max", "ultra"])

    def test_unknown_model_or_empty_list_is_no_info(self):
        self.assertIsNone(self.p.model_effort_levels("gpt-6-astra"))
        self.assertIsNone(self.p.model_effort_levels("no-levels"))
        self.assertIsNone(self.p.model_effort_levels(""))

    def test_missing_or_corrupt_cache_is_no_info(self):
        os.remove(self.cache)
        self.assertIsNone(self.p.model_effort_levels("gpt-5.5"))
        with open(self.cache, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(self.p.model_effort_levels("gpt-5.5"))

    def test_unsupported_effort_is_clamped_supported_is_untouched(self):
        self.assertEqual(self.p.resolve_effort("gpt-5.5", "max"), "xhigh")
        self.assertEqual(self.p.resolve_effort("gpt-5.6-luna", "max"), "max")
        self.assertEqual(self.p.resolve_effort("gpt-5.6-terra", "xhigh"), "xhigh")

    def test_model_missing_from_cache_passes_through(self):
        self.assertEqual(self.p.resolve_effort("gpt-6-astra", "max"), "max")
        self.assertEqual(self.p.resolve_effort("gpt-6-astra", ""), "")


class OtherProvidersPassThroughTests(unittest.TestCase):
    """Değer yeniden yazan yardımcı tüm sağlayıcılara karşı taranır (sonnet-refresh v1 dersi,
    2026-10-08): bilgisi olmayan sağlayıcıda HİÇBİR değer değişmemeli."""

    # Gerçek filodan (2026-10-14 instances.json + canlı süreçler) alınan (cli, model, effort)
    FLEET = [
        ("claude", "claude-sonnet-5", "max"), ("claude", "claude-sonnet-5-5", "max"),
        ("claude", "claude-opus-5", "max"), ("claude", "claude-opus-5-5", "max"),
        ("claude", "claude-fable-5-1", "max"), ("claude", "claude-sonnet-5", "high"),
        ("claude", "fable", "low"), ("claude", "claude-sonnet-5", ""),
        ("copilot", "grok-4.6", "xhigh"), ("copilot", "kimi-k3", "xhigh"), ("copilot", "grok-4.6", ""),
        ("ucli", "deepseek-v4-flash", "high"), ("ucli", "glm-5.3", "high"), ("ucli", "auto", "high"),
        ("ucli", "deepseek-v4-flash", "-"),
        ("shell", "-", "-"), ("shell", "-", ""),
    ]

    def test_fleet_values_pass_through_unchanged(self):
        for cli, model, eff in self.FLEET:
            p = PROVIDERS[cli]
            self.assertIsNone(p.model_effort_levels(model), (cli, model))
            self.assertEqual(p.resolve_effort(model, eff), eff, (cli, model, eff))
            self.assertEqual(p.effort_levels_for(model), p.effort_levels(), (cli, model))

    def test_unknown_values_are_not_rewritten_either(self):
        for cli in ("claude", "copilot", "ucli", "shell"):
            self.assertEqual(PROVIDERS[cli].resolve_effort("whatever", "weird-level"), "weird-level", cli)
            self.assertIsNone(PROVIDERS[cli].resolve_effort("whatever", None), cli)

    def test_only_agy_and_codex_override_model_levels(self):
        overriding = {n for n, p in PROVIDERS.items()
                      if type(p).model_effort_levels is not type(PROVIDERS["claude"]).model_effort_levels}
        self.assertEqual(overriding, {"agy", "codex"})


class SpawnWiringTests(unittest.TestCase):
    """`spawn_session` TEK geçit: effort build_inner_command'a çözülmüş haliyle gider."""

    def run_spawn(self, provider, model, effort):
        with mock.patch.object(spawn, "get_provider", return_value=provider), \
                mock.patch.object(spawn, "_ids_held_by_others", return_value=frozenset()), \
                mock.patch.object(spawn, "detect_display", return_value=":0"), \
                mock.patch.object(provider, "resolve_resume_id", return_value=None), \
                mock.patch.object(provider, "build_inner_command", return_value="agy --x") as bic, \
                mock.patch.object(spawn, "diag_log") as dlog:
            spawn.spawn_session("t", "/tmp", model, effort=effort, dry_run=True, cli="agy")
        return bic, dlog

    def test_adjusted_effort_reaches_the_command_and_is_logged(self):
        bic, dlog = self.run_spawn(agy_with_list(PRO_PLAN_LIST), "gemini-3.1-pro-high", "max")
        self.assertEqual(bic.call_args.args[3], "high")
        dlog.assert_called_once()
        self.assertEqual(dlog.call_args.args[0], "spawn_effort_adjusted")
        self.assertEqual((dlog.call_args.kwargs["requested"], dlog.call_args.kwargs["used"]), ("max", "high"))

    def test_unchanged_effort_is_not_logged(self):
        bic, dlog = self.run_spawn(agy_with_list(PRO_PLAN_LIST), "gemini-3.8-flash-high", "high")
        self.assertEqual(bic.call_args.args[3], "high")
        dlog.assert_not_called()

    def test_resolver_failure_never_blocks_the_spawn(self):
        p = agy_with_list(PRO_PLAN_LIST)
        with mock.patch.object(p, "resolve_effort", side_effect=RuntimeError("boom")):
            bic, dlog = self.run_spawn(p, "gemini-3.1-pro-high", "max")
        self.assertEqual(bic.call_args.args[3], "max")  # istenen aynen geçti
        dlog.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""ucli `--effort` filoya geçiyor, modelin kabul ettiği doğrulanırsa (stdlib unittest).

Çalıştırma:  python3 py/tests/test_ucli_effort.py -v

Kapsadığı iş (TODO.md 2026-10-17 (1), kullanıcı kararı "ucli --effort bağla"): bayraksız ucli, ölçülen en pahalı
seçenekti (unified-cli bench/token-economy: bayraksız 205K kota, medium 74K, high 105K). Panelde seçili effort ön
ayarı (medium/high) artık aynı adla geçer. CANLI bulgu (aynı gün, Evren'e küçük istekler): gemma-4-31b alanı HTTP 400
ile reddediyor, bu yüzden bayrak YALNIZ Evren `/v1/models` `capabilities.reasoning_effort: true` diyen modellere
gider; ikili bayrağı tanımıyorsa, katalog çekilemediyse ya da `ucli_limits.reasoning_effort` = `off` ise komut satırı
BİREBİR eskisi. Gerçek settings.json'a, gerçek ucli ikilisine, ağa, docker'a ya da tmux'a DOKUNMAZ.
"""
import json
import os
import shlex
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import settings  # noqa: E402
from claudeops import ucli_client  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402

HELP_NEW = """Usage: ucli chat [OPTIONS]

Options:
      --repl
      --request-timeout-secs <REQUEST_TIMEOUT_SECS>
      --effort <EFFORT>
          [possible values: low, medium, high, max]
"""
HELP_NO_EFFORT = "Usage: ucli chat [OPTIONS]\n\nOptions:\n      --repl\n      --request-timeout-secs <S>\n"
FLAG = "--effort"

# Evren `GET /v1/models` yanıtının (2026-10-17, canlı) ilgili parçaları.
CAPS = {
    "deepseek-v4-flash": {"reasoning_effort": True, "reasoning_effort_values": None, "reasoning_effort_aliases": None},
    "glm-5.3": {"reasoning_effort": True, "reasoning_effort_values": None,
                "reasoning_effort_aliases": {"medium": "high", "minimal": "low"}},
    "gemma-4-31b": {"reasoning_effort": False, "reasoning_effort_values": None, "reasoning_effort_aliases": None},
    "auto": {"reasoning_effort": False, "reasoning_effort_values": None, "reasoning_effort_aliases": None},
    "only-low-high": {"reasoning_effort": True, "reasoning_effort_values": ["low", "high"],
                      "reasoning_effort_aliases": None},
    "strict": {"reasoning_effort": True, "reasoning_effort_values": ["low"], "reasoning_effort_aliases": None},
}


def models_payload():
    data = [{"id": mid, "object": "model", "task": "chat", "capabilities": caps} for mid, caps in CAPS.items()]
    data.append({"id": "qwen3-embedding-8b", "object": "model", "task": "embedding",
                 "capabilities": {"reasoning_effort": True}})
    data.append({"id": "no-caps", "object": "model", "task": "chat"})
    return {"object": "list", "data": data}


class FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_ucli(directory, help_text):
    path = Path(directory) / "ucli"
    path.write_text("#!/bin/sh\ncat <<'EOF'\n" + help_text + "EOF\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        ucli_client._HELP_CACHE.clear()
        self.addCleanup(ucli_client._HELP_CACHE.clear)
        self.events = []
        self.mode = "auto"
        self.caps = dict(CAPS)
        for p in (mock.patch.object(up, "diag_log", lambda event, **kw: self.events.append((event, kw))),
                  mock.patch.object(up, "ucli_reasoning_mode", lambda: self.mode),
                  # canlı katalog yerine bu testin haritası; TTL'li ağ çekimi HİÇ tetiklenmez
                  mock.patch.object(up, "_live_models", lambda: []),
                  mock.patch.object(up, "_LIVE_CAPS", self.caps)):
            p.start()
            self.addCleanup(p.stop)


class ReasoningModeTests(unittest.TestCase):
    def mode(self, ucli_limits):
        with mock.patch.object(settings, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, "ucli_limits": ucli_limits}):
            return settings.ucli_reasoning_mode()

    def test_unset_empty_and_unknown_values_mean_auto(self):
        for value in (None, "", " ", "turbo", "5", "mid"):
            with self.subTest(value=value):
                self.assertEqual(self.mode({"reasoning_effort": value}), "auto")
        self.assertEqual(self.mode({}), "auto")

    def test_off_words_switch_it_off(self):
        for value in ("off", "OFF", " 0 ", "false", "no", "kapali", "none"):
            with self.subTest(value=value):
                self.assertEqual(self.mode({"reasoning_effort": value}), "off")

    def test_a_named_level_forces_that_level_case_insensitively(self):
        for value in ("low", "medium", "HIGH", " max "):
            with self.subTest(value=value):
                self.assertEqual(self.mode({"reasoning_effort": value}), value.strip().lower())

    def test_a_non_dict_ucli_limits_is_tolerated(self):
        with mock.patch.object(settings, "load_settings", lambda: {"ucli_limits": ["x"]}):
            self.assertEqual(settings.ucli_reasoning_mode(), "auto")

    def test_it_does_not_leak_into_the_numeric_overrides(self):
        with mock.patch.object(settings, "load_settings",
                               lambda: {**settings.DEFAULT_SETTINGS, "ucli_limits": {"reasoning_effort": "high", "max_steps": "9"}}):
            self.assertEqual(settings.ucli_limit_overrides(), {"max_steps": 9})


class CatalogTests(unittest.TestCase):
    """`_fetch_live_models` model listesiyle AYNI çekimden yetenekleri de saklar."""

    def setUp(self):
        for p in (mock.patch.object(up, "byok_env_for", lambda cli: {"UCLI_API_KEY": "k"}),
                  mock.patch.object(up, "_LIVE_CAPS", {}),
                  mock.patch.object(up, "_LIVE_MODEL_CACHE", None),
                  mock.patch.object(up, "_LIVE_MODEL_CACHE_TS", 0.0),
                  mock.patch.object(up, "DEFAULT_ENDPOINT", "https://evren.invalid/v1")):
            p.start()
            self.addCleanup(p.stop)

    def fetch(self, payload):
        with mock.patch.object(up.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse(payload)):
            return up._fetch_live_models()

    def test_only_chat_models_are_listed_and_their_capabilities_kept(self):
        ids = self.fetch(models_payload())
        self.assertEqual(ids, list(CAPS) + ["no-caps"])
        self.assertNotIn("qwen3-embedding-8b", up._LIVE_CAPS)
        self.assertNotIn("no-caps", up._LIVE_CAPS)   # yetenek alanı olmayan model: bilinmiyor
        self.assertIs(up._LIVE_CAPS["gemma-4-31b"]["reasoning_effort"], False)
        self.assertIs(up._LIVE_CAPS["deepseek-v4-flash"]["reasoning_effort"], True)

    def test_a_failed_or_empty_fetch_keeps_the_previous_map(self):
        self.fetch(models_payload())
        before = dict(up._LIVE_CAPS)
        self.assertIsNone(self.fetch({"data": []}))
        self.assertEqual(up._LIVE_CAPS, before)
        with mock.patch.object(up.urllib.request, "urlopen", side_effect=OSError("ağ yok")):
            self.assertIsNone(up._fetch_live_models())
        self.assertEqual(up._LIVE_CAPS, before)

    def test_without_a_key_nothing_is_fetched(self):
        with mock.patch.object(up, "byok_env_for", lambda cli: {}), \
                mock.patch.object(up.urllib.request, "urlopen", side_effect=AssertionError("ağa çıkmamalı")):
            self.assertIsNone(up._fetch_live_models())
        self.assertEqual(up._LIVE_CAPS, {})

    def test_model_choices_and_the_effort_gate_share_one_fetch(self):
        calls = []

        def urlopen(req, timeout=None):
            calls.append(req.full_url)
            return FakeResponse(models_payload())

        with mock.patch.object(up.urllib.request, "urlopen", urlopen):
            ids = up.UcliProvider().model_choices()
            self.assertEqual(up.reasoning_effort_for("deepseek-v4-flash", "high"), "high")
            self.assertIsNone(up.reasoning_effort_for("gemma-4-31b", "high"))
        self.assertIn("deepseek-v4-flash", ids)
        self.assertEqual(calls, ["https://evren.invalid/v1/models"])   # TTL içinde ikinci istek YOK


class ReasoningEffortForTests(TmpCase):
    def test_a_model_that_declares_support_gets_the_level(self):
        self.assertEqual(up.reasoning_effort_for("deepseek-v4-flash", "high"), "high")
        self.assertEqual(up.reasoning_effort_for("deepseek-v4-flash", "medium"), "medium")

    def test_gemma_which_rejects_the_field_gets_nothing(self):
        """Canlı bulgu 2026-10-17: HTTP 400 "'reasoning_effort' parametresini desteklemiyor"."""
        self.assertIsNone(up.reasoning_effort_for("gemma-4-31b", "high"))
        self.assertIsNone(up.reasoning_effort_for("auto", "high"))

    def test_an_unknown_model_or_an_empty_catalog_gets_nothing(self):
        self.assertIsNone(up.reasoning_effort_for("hic-yok", "high"))
        self.caps.clear()
        self.assertIsNone(up.reasoning_effort_for("deepseek-v4-flash", "high"))

    def test_a_malformed_capabilities_entry_is_tolerated(self):
        self.caps["bozuk"] = "evet"
        self.caps["bos"] = {}
        self.caps["metin"] = {"reasoning_effort": "true"}   # yalnız gerçek True kabul
        for model in ("bozuk", "bos", "metin"):
            with self.subTest(model=model):
                self.assertIsNone(up.reasoning_effort_for(model, "high"))

    def test_an_allowed_values_list_restricts_the_level_unless_aliased(self):
        self.assertEqual(up.reasoning_effort_for("only-low-high", "high"), "high")
        self.assertIsNone(up.reasoning_effort_for("only-low-high", "medium"))
        self.assertIsNone(up.reasoning_effort_for("strict", "high"))
        # glm-5.3: values null + medium -> high takma adı: medium'u kendisi çözer, geçmesi güvenli
        self.assertEqual(up.reasoning_effort_for("glm-5.3", "medium"), "medium")
        self.caps["glm-5.3"] = {**CAPS["glm-5.3"], "reasoning_effort_values": ["low", "high"]}
        self.assertEqual(up.reasoning_effort_for("glm-5.3", "medium"), "medium")   # takma ad listede olmasa da geçerli


class EffortArgsTests(TmpCase):
    def test_a_capable_model_and_a_new_binary_get_the_session_preset(self):
        b = fake_ucli(self.dir, HELP_NEW)
        self.assertEqual(up._effort_args(b, "deepseek-v4-flash", "high", "vc"), [FLAG, "high"])
        self.assertEqual(up._effort_args(b, "deepseek-v4-flash", "medium", "vc"), [FLAG, "medium"])
        self.assertEqual(self.events, [])

    def test_off_is_silent_and_sends_nothing(self):
        self.mode = "off"
        b = fake_ucli(self.dir, HELP_NEW)
        self.assertEqual(up._effort_args(b, "deepseek-v4-flash", "high", "vc"), [])
        self.assertEqual(self.events, [])

    def test_a_named_level_overrides_the_preset_but_not_the_model_gate(self):
        self.mode = "low"
        b = fake_ucli(self.dir, HELP_NEW)
        self.assertEqual(up._effort_args(b, "deepseek-v4-flash", "high", "vc"), [FLAG, "low"])
        self.assertEqual(up._effort_args(b, "gemma-4-31b", "high", "vc"), [])

    def test_an_old_binary_gets_nothing_and_the_log_says_why(self):
        b = fake_ucli(self.dir, HELP_NO_EFFORT)
        self.assertEqual(up._effort_args(b, "deepseek-v4-flash", "high", "vc"), [])
        self.assertEqual([(e, kw["name"], kw["flag"]) for e, kw in self.events],
                         [("ucli_flag_unsupported", "vc", FLAG)])

    def test_a_model_that_rejects_the_field_is_skipped_and_logged(self):
        b = fake_ucli(self.dir, HELP_NEW)
        self.assertEqual(up._effort_args(b, "gemma-4-31b", "high", "vc"), [])
        self.assertEqual([(e, kw["name"], kw["model"], kw["level"]) for e, kw in self.events],
                         [("ucli_effort_skipped", "vc", "gemma-4-31b", "high")])

    def test_no_model_and_a_missing_binary_give_nothing_instead_of_raising(self):
        b = fake_ucli(self.dir, HELP_NEW)
        self.assertEqual(up._effort_args(b, None, "high", "vc"), [])
        self.assertEqual(up._effort_args(b, "", "high", "vc"), [])
        self.assertEqual(up._effort_args(str(self.dir / "yok"), "deepseek-v4-flash", "high", "vc"), [])


class BuildInnerCommandTests(TmpCase):
    CWD = "/w/proj"

    def setUp(self):
        super().setUp()
        self.binary = fake_ucli(self.dir, HELP_NEW)
        for p in (mock.patch.object(up, "resolve_binary", lambda: self.binary),
                  mock.patch.object(up, "_sync_api_key_file", lambda: False),
                  mock.patch.object(up, "ucli_limit_overrides", lambda: {}),
                  mock.patch.object(up, "ucli_web_config", lambda: {})):   # web kapalı: docker'a hiç inilmez
            p.start()
            self.addCleanup(p.stop)

    def baseline_argv(self, effort="high", model="deepseek-v4-flash"):
        lim = up._EFFORT_LIMITS[effort]
        return [self.binary, "--root", self.CWD, "chat", "--repl", "--endpoint", up._ENDPOINT,
                "--max-steps", str(lim["max_steps"]), "--max-context-kib", str(lim["max_context_kib"]),
                "--max-tool-calls", str(lim["max_tool_calls"]), "--max-output-tokens", str(lim["max_output_tokens"]),
                "--pretty", "--session", "vc", "--status-file", "--model", model, "--allow-edit",
                "--request-timeout-secs", "600"]

    def build(self, effort="high", model="deepseek-v4-flash"):
        return up.UcliProvider().build_inner_command(self.CWD, model, "allow-edit", effort, None, "", "vc")

    def test_the_preset_name_rides_along_as_the_last_flag(self):
        self.assertEqual(shlex.split(self.build("high")), self.baseline_argv("high") + [FLAG, "high"])
        self.assertEqual(shlex.split(self.build("medium")), self.baseline_argv("medium") + [FLAG, "medium"])

    def test_an_unknown_or_empty_effort_falls_back_to_medium_for_the_flag_too(self):
        """Limitler zaten sessizce medium'a düşüyor (eski oturumlarda effort '-' ya da boş olabilir)."""
        for effort in (None, "", "-", "ultra"):
            with self.subTest(effort=effort):
                self.assertEqual(shlex.split(self.build(effort)), self.baseline_argv("medium") + [FLAG, "medium"])

    def test_gemma_gets_the_command_byte_identical_to_before(self):
        self.assertEqual(self.build("high", "gemma-4-31b"),
                         " ".join(shlex.quote(a) for a in self.baseline_argv("high", "gemma-4-31b")))

    def test_an_old_binary_gets_the_command_byte_identical_to_before(self):
        self.binary = fake_ucli(self.dir, HELP_NO_EFFORT)
        self.assertEqual(self.build(), " ".join(shlex.quote(a) for a in self.baseline_argv()))

    def test_off_gets_the_command_byte_identical_to_before(self):
        self.mode = "off"
        self.assertEqual(self.build(), " ".join(shlex.quote(a) for a in self.baseline_argv()))

    def test_the_api_key_wrapper_keeps_the_flag(self):
        with mock.patch.object(up, "_sync_api_key_file", lambda: True):
            cmd = self.build()
        self.assertTrue(cmd.startswith("sh -c "))
        self.assertIn(f"{FLAG} high", shlex.split(cmd)[2])

    def test_every_effort_preset_still_round_trips_through_the_running_command(self):
        """`--effort` effort ön ayarının parçası DEĞİL: çalışan komut satırından effort adı yine dört sayıdan okunur
        (bayrağı taşımayan eski oturumlar 'bilinmiyor'a düşmesin)."""
        for name in up._EFFORT_LIMITS:
            with self.subTest(effort=name):
                info = up.UcliProvider().extract_info(shlex.split(self.build(name)))
                self.assertEqual((info["effort"], info["model"], info["permission_mode"], info["sid"]),
                                 (name, "deepseek-v4-flash", "allow-edit", "vc"))
        self.assertNotIn("reasoning_effort", next(iter(up._EFFORT_LIMITS.values())))

    def test_the_command_is_still_recognised_as_a_ucli_process(self):
        argv = shlex.split(self.build())
        self.assertTrue(up.UcliProvider().matches_proc(argv))
        self.assertEqual(up.UcliProvider().extract_name(None, argv), "vc")


class RealBinaryTests(unittest.TestCase):
    def test_the_delivered_binary_knows_the_flag_when_it_is_new_enough(self):
        """Teslim edilmiş gerçek kopya yoksa ya da eskiyse atlanır (kopya makineye özel, git'te değil)."""
        real = ucli_client.OWN_UCLI
        if not real.is_file():
            self.skipTest("bin/ucli yok")
        if not ucli_client.binary_supports_flag(str(real), FLAG):
            self.skipTest("bin/ucli bu bayraktan önceki bir sürüm")
        self.assertFalse(ucli_client.binary_supports_flag(str(real), "--effort-yok"))


if __name__ == "__main__":
    unittest.main()

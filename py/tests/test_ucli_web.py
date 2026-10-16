"""ucli web özellikleri (unified-cli be4448a) claudeops'tan açılan oturumlara bağlanıyor (stdlib unittest).

Çalıştırma:  python3 py/tests/test_ucli_web.py -v

Kapsadığı iş (TODO.md "ucli web özellikleri", 2026-10-16): `web_search` / `fetch_url` ucli'de varsayılan
KAPALI bayraklar; claudeops spawn argv'si bunları hiç geçirmiyordu. Artık `settings.json`'ın `ucli_web`
alanı doluysa ve ikili bayrağı tanıyorsa geçiyor; boşsa argv BİREBİR eskisi. Gerçek settings.json'a,
gerçek ucli ikilisine, ağa ya da tmux'a DOKUNMAZ (sahte ikili = küçük kabuk betiği).
"""
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

HELP_BOTH = """Usage: ucli chat [OPTIONS]

Options:
      --allow-fetch
          Offer fetch_url to the model
      --allow-fetch-domain <ALLOW_FETCH_DOMAIN>
          A domain fetch_url may reach
      --search-url <SEARCH_URL>
          Offer web_search to the model
      --search-flavor <SEARCH_FLAVOR>
          searxng or brave
"""
HELP_FETCH_ONLY = HELP_BOTH.split("      --search-url")[0]
HELP_OLD = "Usage: ucli chat [OPTIONS]\n\nOptions:\n      --repl\n      --allow-edit\n"
# `--allow-fetch-domain` var, `--allow-fetch` YOK: tam bayrak eşleşmesini zorlar
HELP_DOMAIN_ONLY = "Options:\n      --allow-fetch-domain <D>\n"


def fake_ucli(directory, help_text, name="ucli", counter=None):
    path = Path(directory) / name
    count = f'echo run >> "{counter}"\n' if counter else ""
    path.write_text("#!/bin/sh\n" + count + "cat <<'EOF'\n" + help_text + "EOF\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        ucli_client._HELP_CACHE.clear()
        self.addCleanup(ucli_client._HELP_CACHE.clear)


def with_web(cfg):
    """`settings.load_settings`ı yamalar: DEFAULT_SETTINGS + verilen `ucli_web`."""
    return mock.patch.object(settings, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, "ucli_web": cfg})


class UcliWebConfigTests(unittest.TestCase):
    def test_empty_unset_and_garbage_mean_web_is_off(self):
        for cfg in ({}, None, "oops", [], 7):
            with with_web(cfg):
                self.assertEqual(settings.ucli_web_config(), {}, cfg)

    def test_valid_searxng_address_defaults_the_flavor(self):
        with with_web({"search_url": "  http://127.0.0.1:8888/search  "}):
            self.assertEqual(settings.ucli_web_config(),
                             {"search_url": "http://127.0.0.1:8888/search", "search_flavor": "searxng"})

    def test_https_and_explicit_flavor_in_any_case(self):
        with with_web({"search_url": "https://s.example.org/search?x=1", "search_flavor": " SearXNG "}):
            self.assertEqual(settings.ucli_web_config()["search_url"], "https://s.example.org/search?x=1")

    def test_brave_is_not_supported_yet_and_fails_closed(self):
        with with_web({"search_url": "https://api.search.brave.com/res/v1/web/search", "search_flavor": "brave",
                       "allow_fetch_domains": "docs.rs"}):
            self.assertEqual(settings.ucli_web_config(), {"allow_fetch_domains": ["docs.rs"]})

    def test_invalid_addresses_keep_search_off(self):
        bad = ["ftp://x.org/search", "http://", "127.0.0.1:8888/search", "javascript:alert(1)", "http://a b/s",
               "http://host:99999/s", "http://h/\x00", "http://h/\ns", "//h/s", "file:///etc/passwd"]
        for url in bad:
            with with_web({"search_url": url}):
                self.assertEqual(settings.ucli_web_config(), {}, repr(url))

    def test_whitespace_around_the_address_is_trimmed_not_rejected(self):
        with with_web({"search_url": "\n  http://h/s \t\n"}):
            self.assertEqual(settings.ucli_web_config()["search_url"], "http://h/s")

    def test_domains_are_split_lowercased_and_deduplicated_in_order(self):
        with with_web({"allow_fetch_domains": "En.Wikipedia.org, docs.rs\ndocs.rs  github.com,,"}):
            self.assertEqual(settings.ucli_web_config()["allow_fetch_domains"],
                             ["en.wikipedia.org", "docs.rs", "github.com"])

    def test_domains_accept_a_list_too(self):
        with with_web({"allow_fetch_domains": ["a.org", " B.org ", ""]}):
            self.assertEqual(settings.ucli_web_config()["allow_fetch_domains"], ["a.org", "b.org"])

    def test_invalid_domains_are_dropped_not_fixed(self):
        bad = ["*.org", "https://a.org", "a.org/path", "a_b.org", "-a.org", "a-.org", "a..org", "a.org:8080",
               "x" * 64 + ".org", ".org", "org.", "a@b.org", "ü.org"]
        with with_web({"allow_fetch_domains": ",".join(bad + ["ok.org"])}):
            self.assertEqual(settings.ucli_web_config()["allow_fetch_domains"], ["ok.org"])

    def test_whitespace_is_a_separator_not_part_of_a_name(self):
        with with_web({"allow_fetch_domains": "a.org b.org"}):
            self.assertEqual(settings.ucli_web_config()["allow_fetch_domains"], ["a.org", "b.org"])

    def test_single_label_hosts_are_valid(self):
        with with_web({"allow_fetch_domains": "localhost"}):
            self.assertEqual(settings.ucli_web_config()["allow_fetch_domains"], ["localhost"])

    def test_domain_count_is_capped(self):
        many = ",".join(f"h{i}.example.org" for i in range(200))
        with with_web({"allow_fetch_domains": many}):
            self.assertEqual(len(settings.ucli_web_config()["allow_fetch_domains"]), 64)

    def test_fetch_domains_do_not_need_a_search_address(self):
        with with_web({"allow_fetch_domains": "docs.rs"}):
            self.assertEqual(settings.ucli_web_config(), {"allow_fetch_domains": ["docs.rs"]})


class SaveSettingsTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.path = str(self.dir / "settings.json")
        p = mock.patch.object(settings, "SETTINGS_JSON", self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_defaults_are_off_and_cache_aware(self):
        s = settings.load_settings()
        self.assertEqual(s["ucli_web"], {})
        self.assertIs(s["handover_cache_aware"], True)

    def test_ucli_web_merges_per_field_and_empty_removes_the_field(self):
        settings.save_settings({"ucli_web": {"search_url": "http://127.0.0.1:8888/search"}})
        settings.save_settings({"ucli_web": {"allow_fetch_domains": "docs.rs"}})
        self.assertEqual(settings.load_settings()["ucli_web"],
                         {"search_url": "http://127.0.0.1:8888/search", "allow_fetch_domains": "docs.rs"})
        settings.save_settings({"ucli_web": {"search_url": ""}})
        self.assertEqual(settings.load_settings()["ucli_web"], {"allow_fetch_domains": "docs.rs"})

    def test_a_list_value_is_stored_as_a_comma_separated_string(self):
        settings.save_settings({"ucli_web": {"allow_fetch_domains": ["a.org", "b.org", " "]}})
        self.assertEqual(settings.load_settings()["ucli_web"]["allow_fetch_domains"], "a.org,b.org")
        self.assertEqual(settings.ucli_web_config()["allow_fetch_domains"], ["a.org", "b.org"])

    def test_other_dict_settings_are_unaffected_by_the_list_handling(self):
        settings.save_settings({"ucli_limits": {"max_steps": "50"}, "provider_bin": {"ucli": "/x/ucli"}})
        s = settings.load_settings()
        self.assertEqual(s["ucli_limits"], {"max_steps": "50"})
        self.assertEqual(s["provider_bin"], {"ucli": "/x/ucli"})

    def test_a_non_dict_stored_value_degrades_to_empty(self):
        Path(self.path).write_text('{"ucli_web": "oops", "handover_cache_aware": false}', encoding="utf-8")
        s = settings.load_settings()
        self.assertEqual(s["ucli_web"], {})
        self.assertIs(s["handover_cache_aware"], False)

    def test_the_escape_hatch_persists(self):
        settings.save_settings({"handover_cache_aware": False})
        self.assertIs(settings.load_settings()["handover_cache_aware"], False)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)


class BinaryFlagProbeTests(TmpCase):
    def test_exact_flag_matching(self):
        b = fake_ucli(self.dir, HELP_BOTH)
        self.assertTrue(ucli_client.binary_supports_flag(b, "--search-url"))
        self.assertTrue(ucli_client.binary_supports_flag(b, "--allow-fetch"))
        self.assertTrue(ucli_client.binary_supports_flag(b, "--allow-fetch-domain"))
        self.assertFalse(ucli_client.binary_supports_flag(b, "--no-such-flag"))

    def test_a_longer_flag_does_not_count_as_its_prefix(self):
        b = fake_ucli(self.dir, HELP_DOMAIN_ONLY)
        self.assertTrue(ucli_client.binary_supports_flag(b, "--allow-fetch-domain"))
        self.assertFalse(ucli_client.binary_supports_flag(b, "--allow-fetch"))

    def test_old_binary_supports_neither(self):
        b = fake_ucli(self.dir, HELP_OLD)
        self.assertFalse(ucli_client.binary_supports_flag(b, "--search-url"))
        self.assertFalse(ucli_client.binary_supports_flag(b, "--allow-fetch"))

    def test_probe_runs_once_per_binary_version_and_again_after_a_new_delivery(self):
        counter = self.dir / "runs"
        b = fake_ucli(self.dir, HELP_OLD, counter=counter)
        for _ in range(3):
            ucli_client.binary_supports_flag(b, "--search-url")
        self.assertEqual(counter.read_text().count("run"), 1)
        fake_ucli(self.dir, HELP_BOTH, counter=counter)           # yeni teslim: boyut/mtime değişti
        self.assertTrue(ucli_client.binary_supports_flag(b, "--search-url"))
        self.assertEqual(counter.read_text().count("run"), 2)

    def test_missing_or_non_executable_binary_is_false_and_not_cached(self):
        self.assertFalse(ucli_client.binary_supports_flag(str(self.dir / "yok"), "--search-url"))
        p = Path(self.dir / "ucli")
        p.write_text("#!/bin/sh\ncat <<'EOF'\n" + HELP_BOTH + "EOF\n", encoding="utf-8")
        p.chmod(0o644)                                              # çalıştırılamaz
        self.assertFalse(ucli_client.binary_supports_flag(str(p), "--search-url"))
        self.assertEqual(ucli_client._HELP_CACHE, {})
        p.chmod(0o755)
        self.assertTrue(ucli_client.binary_supports_flag(str(p), "--search-url"))

    def test_empty_help_output_is_not_cached(self):
        b = fake_ucli(self.dir, "")
        self.assertFalse(ucli_client.binary_supports_flag(b, "--search-url"))
        self.assertEqual(ucli_client._HELP_CACHE, {})

    def test_the_real_delivered_binary_knows_the_web_flags_when_it_is_new_enough(self):
        """Teslim edilmiş gerçek kopya yoksa ya da eskiyse atlanır (kopya makineye özel, git'te değil)."""
        real = ucli_client.OWN_UCLI
        if not real.is_file() or not ucli_client.binary_supports_flag(str(real), "--search-url"):
            self.skipTest("bin/ucli yok ya da web bayraklarından önceki bir sürüm")
        self.assertTrue(ucli_client.binary_supports_flag(str(real), "--allow-fetch"))
        self.assertFalse(ucli_client.binary_supports_flag(str(real), "--no-such-flag"))


class WebArgsTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.events = []
        p = mock.patch.object(up, "diag_log", lambda event, **kw: self.events.append((event, kw)))
        p.start()
        self.addCleanup(p.stop)

    CFG_BOTH = {"search_url": "http://127.0.0.1:8888/search?lang=tr&safe=1",
                "allow_fetch_domains": "en.wikipedia.org, docs.rs"}

    def args(self, help_text, cfg):
        b = fake_ucli(self.dir, help_text)
        with with_web(cfg):
            return up._web_args(b, "vc")

    def test_nothing_configured_adds_nothing_and_never_probes(self):
        b = str(self.dir / "never-created")
        with with_web({}), mock.patch.object(up, "binary_supports_flag", side_effect=AssertionError("yoklandı")):
            self.assertEqual(up._web_args(b, "vc"), [])

    def test_both_capabilities_on_a_new_binary(self):
        self.assertEqual(
            self.args(HELP_BOTH, self.CFG_BOTH),
            ["--search-url", "http://127.0.0.1:8888/search?lang=tr&safe=1", "--search-flavor", "searxng",
             "--allow-fetch", "--allow-fetch-domain", "en.wikipedia.org", "--allow-fetch-domain", "docs.rs"])
        self.assertEqual(self.events, [])

    def test_search_only_adds_no_fetch_flags(self):
        self.assertEqual(self.args(HELP_BOTH, {"search_url": "http://127.0.0.1:8888/search"}),
                         ["--search-url", "http://127.0.0.1:8888/search", "--search-flavor", "searxng"])

    def test_fetch_only_adds_no_search_flags(self):
        self.assertEqual(self.args(HELP_BOTH, {"allow_fetch_domains": "docs.rs"}),
                         ["--allow-fetch", "--allow-fetch-domain", "docs.rs"])

    def test_a_binary_that_only_has_fetch_drops_search_and_says_so(self):
        got = self.args(HELP_FETCH_ONLY, self.CFG_BOTH)
        self.assertEqual(got, ["--allow-fetch", "--allow-fetch-domain", "en.wikipedia.org",
                               "--allow-fetch-domain", "docs.rs"])
        self.assertEqual([(e, kw["flag"]) for e, kw in self.events], [("ucli_web_flag_unsupported", "--search-url")])

    def test_an_old_binary_gets_no_web_flags_at_all_so_spawn_cannot_crash(self):
        self.assertEqual(self.args(HELP_OLD, self.CFG_BOTH), [])
        self.assertEqual(sorted(kw["flag"] for _, kw in self.events), ["--allow-fetch", "--search-url"])


class BuildInnerCommandTests(TmpCase):
    CWD = "/w/proj"

    def setUp(self):
        super().setUp()
        self.binary = fake_ucli(self.dir, HELP_BOTH)
        for p in (mock.patch.object(up, "resolve_binary", lambda: self.binary),
                  mock.patch.object(up, "_sync_api_key_file", lambda: False),
                  mock.patch.object(up, "ucli_limit_overrides", lambda: {}),
                  mock.patch.object(up, "diag_log", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)

    def baseline_argv(self, effort="high", model="deepseek-v4-flash", allow_edit=True):
        lim = up._EFFORT_LIMITS[effort]
        argv = [self.binary, "--root", self.CWD, "chat", "--repl", "--endpoint", up._ENDPOINT,
                "--max-steps", str(lim["max_steps"]), "--max-context-kib", str(lim["max_context_kib"]),
                "--max-tool-calls", str(lim["max_tool_calls"]), "--max-output-tokens", str(lim["max_output_tokens"]),
                "--pretty", "--session", "vc", "--status-file", "--model", model]
        return argv + (["--allow-edit"] if allow_edit else [])

    def build(self, cfg, **kw):
        with with_web(cfg):
            return up.UcliProvider().build_inner_command(
                self.CWD, kw.get("model", "deepseek-v4-flash"), kw.get("permission_mode", "allow-edit"),
                kw.get("effort", "high"), None, "", "vc")

    def test_default_command_is_byte_identical_to_before(self):
        self.assertEqual(self.build({}), " ".join(shlex.quote(a) for a in self.baseline_argv()))

    def test_web_flags_are_appended_after_everything_else(self):
        inner = self.build(ProviderCfg.BOTH)
        argv = shlex.split(inner)
        base = self.baseline_argv()
        self.assertEqual(argv[:len(base)], base)
        self.assertEqual(argv[len(base):],
                         ["--search-url", "http://127.0.0.1:8888/search?lang=tr&safe=1", "--search-flavor", "searxng",
                          "--allow-fetch", "--allow-fetch-domain", "en.wikipedia.org",
                          "--allow-fetch-domain", "docs.rs"])

    def test_url_metacharacters_survive_shell_quoting(self):
        inner = self.build({"search_url": "http://127.0.0.1:8888/search?q=a&b=$(x);c"})
        argv = shlex.split(inner)
        self.assertEqual(argv[argv.index("--search-url") + 1], "http://127.0.0.1:8888/search?q=a&b=$(x);c")

    def test_read_only_sessions_get_web_too_and_no_allow_edit(self):
        argv = shlex.split(self.build({"allow_fetch_domains": "docs.rs"}, permission_mode="read-only"))
        self.assertNotIn("--allow-edit", argv)
        self.assertIn("--allow-fetch", argv)

    def test_api_key_wrapper_keeps_the_flags_and_no_secret_enters_argv(self):
        with mock.patch.object(up, "_sync_api_key_file", lambda: True):
            cmd = self.build(ProviderCfg.BOTH)
        self.assertTrue(cmd.startswith("sh -c "))
        inner = shlex.split(cmd)[2]
        self.assertIn('UCLI_API_KEY="$(cat ', inner)
        self.assertIn("--allow-fetch-domain docs.rs", inner)

    def test_running_command_parsing_is_unaffected_by_the_new_flags(self):
        """Çalışan komut satırı ayrıştırması (model/izin/sid/effort) web bayraklarıyla DEĞİŞMEZ.
        (`effort` değerinin kendisine bakılmaz: `extract_info`nun `--max-output-tokens`u ayrıştırmaması
        eski, bu işten bağımsız bir hata; karşılaştırma web'li ve web'siz komutun AYNI sonucu vermesi.)"""
        with_flags = shlex.split(self.build(ProviderCfg.BOTH))
        without = shlex.split(self.build({}))
        self.assertNotEqual(with_flags, without)
        self.assertEqual(up.UcliProvider().extract_info(with_flags), up.UcliProvider().extract_info(without))
        info = up.UcliProvider().extract_info(with_flags)
        self.assertEqual((info["model"], info["permission_mode"], info["sid"]),
                         ("deepseek-v4-flash", "allow-edit", "vc"))
        self.assertTrue(up.UcliProvider().matches_proc(with_flags))
        self.assertEqual(up.UcliProvider().extract_name(None, with_flags), "vc")


class ProviderCfg:
    BOTH = {"search_url": "http://127.0.0.1:8888/search?lang=tr&safe=1",
            "allow_fetch_domains": "en.wikipedia.org, docs.rs"}


if __name__ == "__main__":
    unittest.main()

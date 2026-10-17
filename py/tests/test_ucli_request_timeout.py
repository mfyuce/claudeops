"""ucli `--request-timeout-secs` filoya geçiyor (stdlib unittest).

Çalıştırma:  python3 py/tests/test_ucli_request_timeout.py -v

Kapsadığı iş (TODO.md 2026-10-16 (8), 2026-10-17): ucli'nin 120 sn'lik istek zaman aşımı filonun ölçülen en pahalı
tek olayı (iptal edilen istek sunucuda yine işlenip sayılıyor, yeniden deneme önbelleksiz dönüyor); claudeops bayrağı
hiç geçirmiyordu. Artık varsayılan 600 sn, Ayarlar'daki `ucli_limits.request_timeout_secs` ile değişir, ikili bayrağı
tanımıyorsa komut satırı BİREBİR eskisi (eski ikili 'unexpected argument' ile spawn anında patlamasın). Gerçek
settings.json'a, gerçek ucli ikilisine, docker'a, ağa ya da tmux'a DOKUNMAZ (sahte ikili = küçük kabuk betiği).
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

HELP_NEW = """Usage: ucli chat [OPTIONS]

Options:
      --repl
      --request-timeout-secs <REQUEST_TIMEOUT_SECS>
          Each individual HTTP request to the model endpoint is cancelled if it runs longer than this
"""
HELP_OLD = "Usage: ucli chat [OPTIONS]\n\nOptions:\n      --repl\n      --allow-edit\n"
FLAG = "--request-timeout-secs"


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
        p = mock.patch.object(up, "diag_log", lambda event, **kw: self.events.append((event, kw)))
        p.start()
        self.addCleanup(p.stop)


class LimitOverridesTests(unittest.TestCase):
    def overrides(self, ucli_limits):
        with mock.patch.object(settings, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, "ucli_limits": ucli_limits}):
            return settings.ucli_limit_overrides()

    def test_the_timeout_is_a_valid_override_as_a_string_or_a_number(self):
        self.assertEqual(self.overrides({"request_timeout_secs": "300"}), {"request_timeout_secs": 300})
        self.assertEqual(self.overrides({"request_timeout_secs": 900}), {"request_timeout_secs": 900})

    def test_unset_empty_and_invalid_values_fall_back_to_the_default(self):
        for bad in (None, "", "0", "-5", "abc", "1.5", " "):
            with self.subTest(value=bad):
                self.assertEqual(self.overrides({"request_timeout_secs": bad}), {})
        self.assertEqual(self.overrides({}), {})

    def test_the_other_overrides_are_unaffected(self):
        self.assertEqual(self.overrides({"max_steps": "50", "request_timeout_secs": "300", "bogus": "1"}),
                         {"max_steps": 50, "request_timeout_secs": 300})


class TimeoutArgsTests(TmpCase):
    def test_a_binary_that_knows_the_flag_gets_the_600_second_default(self):
        b = fake_ucli(self.dir, HELP_NEW)
        self.assertEqual(up._timeout_args(b, {}, "vc"), [FLAG, "600"])
        self.assertEqual(up._REQUEST_TIMEOUT_SECS, 600)
        self.assertEqual(self.events, [])

    def test_the_settings_override_replaces_the_default(self):
        b = fake_ucli(self.dir, HELP_NEW)
        self.assertEqual(up._timeout_args(b, {"request_timeout_secs": 300}, "vc"), [FLAG, "300"])

    def test_an_old_binary_gets_nothing_and_the_log_says_why(self):
        b = fake_ucli(self.dir, HELP_OLD)
        self.assertEqual(up._timeout_args(b, {}, "vc"), [])
        self.assertEqual([(e, kw["name"], kw["flag"]) for e, kw in self.events],
                         [("ucli_flag_unsupported", "vc", FLAG)])

    def test_a_missing_binary_gets_nothing_instead_of_raising(self):
        self.assertEqual(up._timeout_args(str(self.dir / "yok"), {}, "vc"), [])


class BuildInnerCommandTests(TmpCase):
    CWD = "/w/proj"

    def setUp(self):
        super().setUp()
        self.overrides = {}
        self.binary = fake_ucli(self.dir, HELP_NEW)
        for p in (mock.patch.object(up, "resolve_binary", lambda: self.binary),
                  mock.patch.object(up, "_sync_api_key_file", lambda: False),
                  mock.patch.object(up, "ucli_limit_overrides", lambda: self.overrides),
                  mock.patch.object(up, "ucli_web_config", lambda: {})):   # web kapalı: docker'a hiç inilmez
            p.start()
            self.addCleanup(p.stop)

    def baseline_argv(self, effort="high"):
        lim = up._EFFORT_LIMITS[effort]
        return [self.binary, "--root", self.CWD, "chat", "--repl", "--endpoint", up._ENDPOINT,
                "--max-steps", str(lim["max_steps"]), "--max-context-kib", str(lim["max_context_kib"]),
                "--max-tool-calls", str(lim["max_tool_calls"]), "--max-output-tokens", str(lim["max_output_tokens"]),
                "--pretty", "--session", "vc", "--status-file", "--model", "deepseek-v4-flash", "--allow-edit"]

    def build(self, effort="high"):
        return up.UcliProvider().build_inner_command(
            self.CWD, "deepseek-v4-flash", "allow-edit", effort, None, "", "vc")

    def test_the_default_command_ends_with_the_600_second_timeout(self):
        self.assertEqual(shlex.split(self.build()), self.baseline_argv() + [FLAG, "600"])

    def test_the_settings_override_reaches_the_command(self):
        self.overrides = {"request_timeout_secs": 300, "max_steps": 7}
        argv = shlex.split(self.build())
        self.assertEqual(argv[argv.index(FLAG) + 1], "300")
        self.assertEqual(argv[argv.index("--max-steps") + 1], "7")   # öbür geçersiz kılmalar eskisi gibi

    def test_an_old_binary_gets_the_command_byte_identical_to_before(self):
        self.binary = fake_ucli(self.dir, HELP_OLD)
        self.assertEqual(self.build(), " ".join(shlex.quote(a) for a in self.baseline_argv()))

    def test_the_api_key_wrapper_keeps_the_flag(self):
        with mock.patch.object(up, "_sync_api_key_file", lambda: True):
            cmd = self.build()
        self.assertTrue(cmd.startswith("sh -c "))
        self.assertIn(f"{FLAG} 600", shlex.split(cmd)[2])

    def test_every_effort_preset_still_round_trips_through_the_running_command(self):
        """Zaman aşımı effort ön ayarının parçası DEĞİL: çalışan komut satırından effort adı yine okunur
        (beşinci sayı ön ayara girseydi, bu bayrağı taşımayan eski oturumlar 'bilinmiyor' olurdu)."""
        for name in up._EFFORT_LIMITS:
            with self.subTest(effort=name):
                info = up.UcliProvider().extract_info(shlex.split(self.build(name)))
                self.assertEqual((info["effort"], info["model"], info["permission_mode"], info["sid"]),
                                 (name, "deepseek-v4-flash", "allow-edit", "vc"))
        self.assertNotIn("request_timeout_secs", next(iter(up._EFFORT_LIMITS.values())))

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
        self.assertFalse(ucli_client.binary_supports_flag(str(real), "--no-such-flag"))


if __name__ == "__main__":
    unittest.main()

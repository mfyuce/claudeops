"""ucli `--stream` claudeops'tan açılan oturumlara AYARLA bağlanıyor (stdlib unittest).

Çalıştırma:  python3 py/tests/test_ucli_stream.py -v

Kapsadığı iş (TODO.md 2026-10-18 (3)): `ucli_limits.stream` "on" ise ve ikili `--stream`'i tanıyorsa komuta `--stream`
eklenir; "off" kapatır; boş/eksik/bozuk değer `UCLI_STREAM_DEFAULT`'a düşer. Eski ikili bayrağı tanımıyorsa komuta
GİRMEZ ('unexpected argument' ile spawn anında ölürdü) ve günlüğe yazılır. Gerçek settings.json'a, gerçek ucli ikilisine,
docker'a, ağa ya da tmux'a DOKUNMAZ (sahte ikili = küçük kabuk betiği; yazma yolu geçici dosyaya yönlendirilir).
"""
import os
import shlex
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claudeops import settings  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from test_ucli_web import TmpCase, fake_ucli  # noqa: E402

HELP_STREAM = """Usage: ucli chat [OPTIONS]

Options:
      --stream
          Ask the model for a streamed response
"""
HELP_OLD = "Usage: ucli chat [OPTIONS]\n\nOptions:\n      --repl\n      --allow-edit\n"


def with_limits(cfg):
    return mock.patch.object(settings, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, "ucli_limits": cfg})


class StreamSettingTests(unittest.TestCase):
    def test_the_shipped_default_is_on(self):
        """Karar (TODO.md 2026-10-18 (3), kullanıcı devretti): ölçümler (7/7 model, usage, gerçek Wi-Fi dalgalanması) akışı
        destekledi, varsayılan AÇIK. Bu test sabiti kilitler, değiştiren bilerek değiştirir."""
        self.assertIs(settings.UCLI_STREAM_DEFAULT, True)

    def test_an_untouched_install_asks_for_the_stream_and_off_still_wins(self):
        with with_limits({}):
            self.assertIs(settings.ucli_stream_enabled(), True)
        with with_limits({"stream": "off"}):
            self.assertIs(settings.ucli_stream_enabled(), False)

    def test_missing_empty_and_garbage_fall_back_to_the_default(self):
        for default in (False, True):
            with mock.patch.object(settings, "UCLI_STREAM_DEFAULT", default):
                for cfg in ({}, None, "oops", [], 7, {"stream": ""}, {"stream": "maybe"}, {"stream": 3}, {"stream": None}):
                    with with_limits(cfg):
                        self.assertIs(settings.ucli_stream_enabled(), default, (default, cfg))

    def test_on_words_enable_in_any_spelling(self):
        for raw in ("on", " ON ", "True", "1", "yes", "evet", "Açık", "enabled"):
            with with_limits({"stream": raw}):
                self.assertIs(settings.ucli_stream_enabled(), True, raw)

    def test_off_words_disable_even_when_the_default_is_on(self):
        with mock.patch.object(settings, "UCLI_STREAM_DEFAULT", True):
            for raw in ("off", "0", "false", "no", "hayır", "kapalı", "disabled", "none"):
                with with_limits({"stream": raw}):
                    self.assertIs(settings.ucli_stream_enabled(), False, raw)

    def test_the_stream_key_is_not_mistaken_for_a_numeric_limit(self):
        with with_limits({"stream": "on", "max_steps": "50"}):
            self.assertEqual(settings.ucli_limit_overrides(), {"max_steps": 50})


class SaveStreamSettingTests(TmpCase):
    """YAZMA YOLU geçici dosyaya yönlendirilir (`settings.SETTINGS_JSON`, `create=True` YOK)."""

    def setUp(self):
        super().setUp()
        self.path = str(self.dir / "settings.json")
        p = mock.patch.object(settings, "SETTINGS_JSON", self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_it_round_trips_and_an_empty_value_goes_back_to_the_default(self):
        settings.save_settings({"ucli_limits": {"stream": "on"}})
        self.assertEqual(settings.load_settings()["ucli_limits"], {"stream": "on"})
        self.assertIs(settings.ucli_stream_enabled(), True)
        settings.save_settings({"ucli_limits": {"stream": ""}})
        self.assertEqual(settings.load_settings()["ucli_limits"], {})
        self.assertIs(settings.ucli_stream_enabled(), settings.UCLI_STREAM_DEFAULT)

    def test_it_does_not_disturb_the_other_limit_fields(self):
        settings.save_settings({"ucli_limits": {"max_tool_calls": "800", "reasoning_effort": "high"}})
        settings.save_settings({"ucli_limits": {"stream": "on"}})
        self.assertEqual(settings.load_settings()["ucli_limits"],
                         {"max_tool_calls": "800", "reasoning_effort": "high", "stream": "on"})
        self.assertEqual(settings.ucli_limit_overrides(), {"max_tool_calls": 800})
        self.assertEqual(settings.ucli_reasoning_mode(), "high")

    def test_a_hand_edited_non_dict_value_degrades_to_the_default(self):
        Path(self.path).write_text('{"ucli_limits": "on"}', encoding="utf-8")
        self.assertIs(settings.ucli_stream_enabled(), settings.UCLI_STREAM_DEFAULT)


class BuildCommandTests(TmpCase):
    CWD = "/w/proj"

    def setUp(self):
        super().setUp()
        self.binary = fake_ucli(self.dir, HELP_STREAM)
        self.diag = mock.Mock()
        for p in (mock.patch.object(up, "resolve_binary", lambda: self.binary),
                  mock.patch.object(up, "_sync_api_key_file", lambda: False),
                  mock.patch.object(up, "ucli_limit_overrides", lambda: {}),
                  mock.patch.object(up, "ucli_web_config", lambda: {}),
                  mock.patch.object(up, "ucli_script_mode", lambda: ""),
                  mock.patch.object(up, "diag_log", self.diag)):
            p.start()
            self.addCleanup(p.stop)

    def build(self, enabled):
        with mock.patch.object(up, "ucli_stream_enabled", lambda: enabled):
            return shlex.split(up.UcliProvider().build_inner_command(
                self.CWD, "deepseek-v4-flash", "allow-edit", "high", None, "", "vc"))

    def test_off_leaves_the_command_without_the_flag(self):
        self.assertNotIn("--stream", self.build(False))
        # sahte ikili başka bayrakları (--effort, --request-timeout-secs) tanımadığı için onlar günlüğe yazar; akış yazmaz
        self.assertFalse([c for c in self.diag.call_args_list if c.kwargs.get("flag") == "--stream"])

    def test_on_adds_exactly_one_bare_flag(self):
        argv = self.build(True)
        self.assertEqual(argv.count("--stream"), 1)
        self.assertIn("--pretty", argv)   # sunum bayrağı, --stream'in yerini almıyor

    def test_an_old_binary_without_the_flag_is_not_given_it_and_the_skip_is_logged(self):
        old = fake_ucli(self.dir, HELP_OLD, name="ucli-old")
        with mock.patch.object(up, "resolve_binary", lambda: old):
            argv = self.build(True)
        self.assertNotIn("--stream", argv)
        self.diag.assert_called_with("ucli_flag_unsupported", name="vc", flag="--stream", binary=old)


if __name__ == "__main__":
    unittest.main()

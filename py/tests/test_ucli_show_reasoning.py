"""ucli `--show-reasoning` ayarla bağlanır (opt-in): ayar açık + ikili tanıyorsa komuta girer; kapalı/tanımıyorsa girmez."""
import os
import shlex
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claudeops import settings  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from test_ucli_web import TmpCase, fake_ucli  # noqa: E402

HELP_YES = "Usage: ucli chat [OPTIONS]\n\nOptions:\n      --show-reasoning\n          Print reasoning to stderr\n"
HELP_OLD = "Usage: ucli chat [OPTIONS]\n\nOptions:\n      --repl\n      --allow-edit\n"


def with_limits(cfg):
    return mock.patch.object(settings, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, "ucli_limits": cfg})


class SettingTests(unittest.TestCase):
    def test_default_off_and_words(self):
        self.assertIs(settings.UCLI_SHOW_REASONING_DEFAULT, False)
        for cfg, want in (({}, False), ({"show_reasoning": ""}, False), ({"show_reasoning": "on"}, True), ({"show_reasoning": "Evet"}, True),
                          ({"show_reasoning": "off"}, False), ({"show_reasoning": "garip"}, False), ("bozuk", False), (None, False)):
            with with_limits(cfg):
                self.assertIs(settings.ucli_show_reasoning_enabled(), want, cfg)


class BuildTests(TmpCase):
    def build(self, help_text, enabled):
        binary = fake_ucli(self.dir, help_text)
        diag = mock.Mock()
        with mock.patch.object(up, "resolve_binary", lambda: binary), mock.patch.object(up, "_sync_api_key_file", lambda: False), \
                mock.patch.object(up, "ucli_limit_overrides", lambda: {}), mock.patch.object(up, "ucli_web_config", lambda: {}), \
                mock.patch.object(up, "ucli_script_mode", lambda: ""), mock.patch.object(up, "diag_log", diag), \
                mock.patch.object(up, "ucli_show_reasoning_enabled", lambda: enabled):
            argv = shlex.split(up.UcliProvider().build_inner_command("/w/proj", "m", "allow-edit", "high", None, "", "vc"))
        return argv, diag

    def test_flag_added_only_when_enabled_and_supported(self):
        self.assertIn("--show-reasoning", self.build(HELP_YES, True)[0])
        self.assertNotIn("--show-reasoning", self.build(HELP_YES, False)[0])

    def test_old_binary_never_gets_the_flag_and_it_is_logged(self):
        argv, diag = self.build(HELP_OLD, True)
        self.assertNotIn("--show-reasoning", argv)
        self.assertTrue(any(c.kwargs.get("flag") == "--show-reasoning" for c in diag.call_args_list))


if __name__ == "__main__":
    unittest.main()

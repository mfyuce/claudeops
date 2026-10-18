"""ucli gömülü betik katmanı (unified-cli 119c8e5, `chat --allow-script[=read|full]`) ve `--allow-create` kipi
claudeops'tan açılan oturumlara bağlanıyor (stdlib unittest).

Çalıştırma:  python3 py/tests/test_ucli_script.py -v

Kapsadığı iş (TODO.md 2026-10-17 (6)): ayar `ucli_script.mode` VARSAYILAN KAPALI (argv BİREBİR eskisi); `read`/`full`
yalnız ikili `--allow-script`'i tanıyorsa `--allow-script=MODE` olarak geçer. Yeni izin kipi `allow-create`
(`--allow-create`: yalnız yeni dosya) panelde ve çalışan komuttan geri okunurken tanınır. Gerçek settings.json'a,
gerçek ucli ikilisine, docker'a, ağa ya da tmux'a DOKUNMAZ (sahte ikili = küçük kabuk betiği).
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
from claudeops.commands import web  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from test_ucli_web import TmpCase, fake_ucli  # noqa: E402

HELP_SCRIPT = """Usage: ucli chat [OPTIONS]

Options:
      --allow-script[=<ALLOW_SCRIPT>]
          Offer run_script
      --allow-create
          Create-only writes
"""
HELP_OLD = "Usage: ucli chat [OPTIONS]\n\nOptions:\n      --repl\n      --allow-edit\n"


def with_script(cfg):
    return mock.patch.object(settings, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, "ucli_script": cfg})


class ScriptModeSettingTests(unittest.TestCase):
    def test_default_and_garbage_mean_off(self):
        for cfg in ({}, None, "oops", [], 7, {"mode": ""}, {"mode": "off"}, {"mode": "maybe"}, {"mode": 3}):
            with with_script(cfg):
                self.assertEqual(settings.ucli_script_mode(), "", cfg)

    def test_read_and_full_in_any_spelling(self):
        for raw, want in (("read", "read"), (" FULL ", "full"), ("Read", "read")):
            with with_script({"mode": raw}):
                self.assertEqual(settings.ucli_script_mode(), want, raw)

    def test_default_settings_carry_the_key(self):
        self.assertEqual(settings.DEFAULT_SETTINGS["ucli_script"], {})


class BuildCommandTests(TmpCase):
    CWD = "/w/proj"

    def setUp(self):
        super().setUp()
        self.binary = fake_ucli(self.dir, HELP_SCRIPT)
        for p in (mock.patch.object(up, "resolve_binary", lambda: self.binary),
                  mock.patch.object(up, "_sync_api_key_file", lambda: False),
                  mock.patch.object(up, "ucli_limit_overrides", lambda: {}),
                  mock.patch.object(up, "ucli_web_config", lambda: {}),
                  mock.patch.object(up, "diag_log", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)

    def build(self, mode, permission_mode="allow-edit"):
        with mock.patch.object(up, "ucli_script_mode", lambda: mode):
            return shlex.split(up.UcliProvider().build_inner_command(
                self.CWD, "deepseek-v4-flash", permission_mode, "high", None, "", "vc"))

    def test_off_leaves_the_command_exactly_as_before(self):
        off = self.build("")
        self.assertFalse([a for a in off if a.startswith("--allow-script")])

    def test_read_and_full_append_one_equals_form_flag(self):
        for mode in ("read", "full"):
            argv = self.build(mode)
            self.assertEqual([a for a in argv if a.startswith("--allow-script")], [f"--allow-script={mode}"])

    def test_old_binary_without_the_flag_is_not_given_it(self):
        old = fake_ucli(self.dir, HELP_OLD, name="ucli-old")
        with mock.patch.object(up, "resolve_binary", lambda: old):
            argv = self.build("full")
        self.assertFalse([a for a in argv if a.startswith("--allow-script")])

    def test_allow_create_mode_passes_only_that_flag(self):
        argv = self.build("", permission_mode="allow-create")
        self.assertIn("--allow-create", argv)
        self.assertNotIn("--allow-edit", argv)

    def test_allow_create_on_a_binary_that_lacks_it_opens_read_only(self):
        old = fake_ucli(self.dir, HELP_OLD, name="ucli-old")
        with mock.patch.object(up, "resolve_binary", lambda: old):
            argv = self.build("", permission_mode="allow-create")
        self.assertNotIn("--allow-create", argv)
        self.assertNotIn("--allow-edit", argv)

    def test_permission_modes_list_and_round_trip_from_the_running_command(self):
        self.assertEqual(up.UcliProvider().permission_modes(), ["read-only", "allow-edit", "allow-create"])
        for mode, want in (("read-only", "read-only"), ("allow-edit", "allow-edit"), ("allow-create", "allow-create")):
            argv = self.build("full", permission_mode=mode)
            info = up.UcliProvider().extract_info(argv, cwd=self.CWD, session_name="vc")
            self.assertEqual(info["permission_mode"], want)


class SaveScriptSettingTests(TmpCase):
    """Panelin Ayarlar seçicisi `POST /api/settings` ile `{"ucli_script": {"mode": ...}}` yollar ("kapalı" = boş string).
    YAZMA YOLU geçici dosyaya yönlendirilir (`settings.SETTINGS_JSON`, `create=True` YOK): bu sınıf gerçek
    ~/.claude/claudeops/settings.json'a asla yazmamalı."""

    def setUp(self):
        super().setUp()
        self.path = str(self.dir / "settings.json")
        p = mock.patch.object(settings, "SETTINGS_JSON", self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_mode_round_trips_and_an_empty_one_switches_the_layer_off(self):
        for mode in ("read", "full"):
            settings.save_settings({"ucli_script": {"mode": mode}})
            self.assertEqual(settings.load_settings()["ucli_script"], {"mode": mode})
            self.assertEqual(settings.ucli_script_mode(), mode)
        settings.save_settings({"ucli_script": {"mode": ""}})            # seçicideki "kapalı"
        self.assertEqual(settings.load_settings()["ucli_script"], {})
        self.assertEqual(settings.ucli_script_mode(), "")

    def test_saving_the_mode_leaves_the_other_ucli_panels_alone(self):
        settings.save_settings({"ucli_limits": {"max_tool_calls": "800"}, "ucli_web": {"allow_fetch_domains": "docs.rs"}})
        settings.save_settings({"ucli_script": {"mode": "full"}})
        s = settings.load_settings()
        self.assertEqual(s["ucli_limits"], {"max_tool_calls": "800"})
        self.assertEqual(s["ucli_web"], {"allow_fetch_domains": "docs.rs"})
        self.assertEqual(s["ucli_script"], {"mode": "full"})

    def test_a_hand_edited_non_dict_value_degrades_to_off(self):
        Path(self.path).write_text('{"ucli_script": "full"}', encoding="utf-8")
        self.assertEqual(settings.load_settings()["ucli_script"], {})
        self.assertEqual(settings.ucli_script_mode(), "")

    def test_the_panel_endpoint_returns_the_field_on_the_wire(self):
        res = web._save_settings({"ucli_script": {"mode": "read"}})
        self.assertTrue(res["ok"])
        self.assertEqual(res["settings"]["ucli_script"], {"mode": "read"})
        self.assertEqual(web._redact_settings_for_wire(settings.load_settings())["ucli_script"], {"mode": "read"})


if __name__ == "__main__":
    unittest.main()

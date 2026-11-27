"""TBD#397 soru 2 (1): UTF-8 olmayan yardım / `mcp add` çıktısı istisna atıp başlatmayı düşürmez; belirsizlikte bayrak
tanınmaz, güvenlik izni bayrağı doğrulanamazsa ret kalır, olay günlüğe girer. Sahte ikililer geçici dizinde."""
import os
import shlex
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import settings, ucli_client  # noqa: E402
from claudeops.providers import claude_provider as claude_p  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.providers.base import McpServerSpec  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.logs = []
        log = lambda event, **kw: self.logs.append((event, kw))
        for p in (mock.patch.object(settings, "SETTINGS_JSON", os.path.join(self.tmp, "settings.json")),
                  mock.patch.object(ucli_client, "diag_log", log, create=True),
                  mock.patch.object(claude_p, "diag_log", log, create=True),
                  mock.patch.object(up, "diag_log", log)):
            p.start()
            self.addCleanup(p.stop)
        for cache in (ucli_client._HELP_CACHE, claude_p._HELP_CACHE):
            cache.clear()
            self.addCleanup(cache.clear)

    def script(self, name, body):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return path

    def events(self, name):
        return [kw for event, kw in self.logs if event == name]


class HelpProbe(_Tmp):
    def test_non_utf8_help_means_no_flags_and_is_logged_once(self):
        for probe, supports in ((ucli_client.chat_help_text, ucli_client.binary_supports_flag),
                                (claude_p.claude_help_text, lambda b, f: claude_p.claude_supports_flag(f, b))):
            self.logs.clear()
            binary = self.script(f"h{len(os.listdir(self.tmp))}", "printf '\\377 --provider\\n'")
            self.assertEqual(probe(binary), "")
            self.assertFalse(supports(binary, "--provider"))
            self.assertEqual(self.events("help_output_not_utf8"), [{"binary": binary}])

    def test_a_fixed_binary_is_probed_again(self):
        binary = self.script("u", "printf '\\377'")
        self.assertEqual(ucli_client.chat_help_text(binary), "")
        self.script("u", "echo '--provider <P>'")
        self.assertTrue(ucli_client.binary_supports_flag(binary, "--provider"))

    def test_the_security_permission_flag_is_still_refused(self):
        binary = self.script("u", "printf '\\377 --allow-exec --allow-exec-cmd\\n'")
        with mock.patch.object(up, "resolve_binary", lambda: binary), \
                mock.patch.object(up, "_sync_api_key_file", lambda: False):
            build = lambda opts: up.UcliProvider().build_inner_command(self.tmp, "m", "allow-edit", "high", None, "",
                                                                       "vc", cli_opts=opts)
            argv = shlex.split(build(None))
            self.assertNotIn("--allow-exec", argv)
            with self.assertRaises(ValueError) as cm:
                build({"exec_cmds": ["cargo"]})
        self.assertNotIsInstance(cm.exception, UnicodeError)
        self.assertTrue(self.events("help_output_not_utf8"))


class McpAdd(_Tmp):
    def register(self, body):
        binary = self.script("u", body)
        return up.register_mcp(binary, self.tmp, McpServerSpec(name="s", command="/c", args=(), allowed_tools=("t",)), "vc")

    def test_success_follows_the_exit_code(self):
        self.assertTrue(self.register("printf '\\377\\n'"))
        self.assertEqual(len(self.events("ucli_mcp_output_not_utf8")), 1)
        self.assertEqual(len(self.events("ucli_mcp_registered")), 1)

    def test_failure_is_reported_not_raised(self):
        self.assertFalse(self.register("printf 'hata \\377' >&2; exit 3"))
        self.assertEqual(self.events("ucli_mcp_register_failed")[0]["error"], "hata �")
        self.assertEqual(len(self.events("ucli_mcp_output_not_utf8")), 1)

    def test_clean_output_logs_nothing_extra(self):
        self.assertTrue(self.register("echo tamam"))
        self.assertEqual(self.events("ucli_mcp_output_not_utf8"), [])


if __name__ == "__main__":
    unittest.main()

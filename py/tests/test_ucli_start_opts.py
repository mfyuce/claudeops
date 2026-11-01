"""Başlat penceresi seçenekleri (`cli_opts`): doğrulama, argv, anahtar dosyası, reddetme, diğer provider'lara sızmama.
Gerçek ayar/anahtar dosyasına DOKUNMAZ (HOME ve byok yamalı)."""
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claudeops import spawn  # noqa: E402
from claudeops import ucli_client  # noqa: E402
from claudeops import ucli_session_opts as so  # noqa: E402
from claudeops.providers import get_provider  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from test_ucli_web import HELP_BOTH, fake_ucli  # noqa: E402

HELP_EXEC = HELP_BOTH + """      --provider <PROVIDER>
      --api-key-env <API_KEY_ENV>
      --allow-exec
      --allow-exec-cmd <CMD>
      --allow-exec-own-glob <G>
      --exec-timeout-secs <N>
"""


class ValidateTests(unittest.TestCase):
    def test_empty_is_ok_and_empty(self):
        self.assertEqual(so.validate_opts(None), ({}, ""))
        self.assertEqual(so.validate_opts({}), ({}, ""))

    def test_unknown_service_rejected(self):
        self.assertTrue(so.validate_opts({"service": "x"})[1])

    def test_shells_and_wrappers_rejected(self):
        for c in ("sh", "bash", "env", "xargs", "find", "sudo", "/bin/ls", "python3:allow-eval"):
            self.assertTrue(so.validate_opts({"exec_cmds": [c]})[1], c)

    def test_glob_needs_cmds_and_must_be_narrow(self):
        self.assertTrue(so.validate_opts({"exec_own_glob": ["tests/**"]})[1])
        for g in ("**", "*", "../x", "/etc/*", "a//b"):
            self.assertTrue(so.validate_opts({"exec_cmds": ["cargo"], "exec_own_glob": [g]})[1], g)
        out, err = so.validate_opts({"exec_cmds": "cargo, pytest", "exec_own_glob": "tests/**", "exec_timeout": "60"})
        self.assertEqual(err, "")
        self.assertEqual(out, {"exec_cmds": ["cargo", "pytest"], "exec_own_glob": ["tests/**"], "exec_timeout": 60})

    def test_timeout_range_and_requires_cmds(self):
        self.assertTrue(so.validate_opts({"exec_cmds": ["cargo"], "exec_timeout": 0})[1])
        self.assertTrue(so.validate_opts({"exec_timeout": 30})[1])


class BuildTests(unittest.TestCase):
    CWD = "/w/proj"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        ucli_client._HELP_CACHE.clear()
        self.addCleanup(ucli_client._HELP_CACHE.clear)
        self.binary = fake_ucli(self._tmp.name, HELP_EXEC)
        self.keys = {}
        for p in (mock.patch.object(up, "resolve_binary", lambda: self.binary),
                  mock.patch.object(up, "_sync_api_key_file", lambda: False),
                  mock.patch.object(up, "ucli_limit_overrides", lambda: {}),
                  mock.patch.object(up, "diag_log", lambda *a, **k: None),
                  mock.patch.object(up, "byok_env_for", lambda cli: dict(self.keys)),
                  mock.patch.object(up, "_service_key_file", lambda s: os.path.join(self._tmp.name, f"key_{s}")),
                  mock.patch.object(up, "_web_args", lambda *a, **k: []),
                  mock.patch.object(up, "_script_args", lambda *a, **k: []),
                  mock.patch.object(up, "_stream_args", lambda *a, **k: []),
                  mock.patch.object(up, "_state_dir_args", lambda *a, **k: []),
                  mock.patch.object(up, "_effort_args", lambda *a, **k: ["--effort", "high"])):
            p.start()
            self.addCleanup(p.stop)

    def build(self, opts=None):
        return up.UcliProvider().build_inner_command(self.CWD, "m", "allow-edit", "high", None, "", "vc", cli_opts=opts)

    def test_no_opts_is_identical_to_before(self):
        self.assertEqual(self.build(None), self.build({}))
        self.assertNotIn("--provider", self.build(None))

    def test_claude_service_swaps_endpoint_once_and_key_stays_out_of_argv(self):
        self.keys = {"ANTHROPIC_API_KEY": "sk-secret"}
        cmd = self.build({"service": "claude"})
        self.assertNotIn("sk-secret", cmd)
        outer = shlex.split(cmd)
        self.assertEqual(outer[:2], ["sh", "-c"])
        inner = outer[2]
        self.assertTrue(inner.startswith('ANTHROPIC_API_KEY="$(cat '))
        argv = shlex.split(inner.split(" exec ", 1)[1])
        self.assertEqual(argv.count("--endpoint"), 1)
        self.assertEqual(argv[argv.index("--endpoint") + 1], "https://api.anthropic.com/v1")
        self.assertEqual(argv[argv.index("--provider") + 1], "anthropic-messages")
        self.assertEqual(argv[argv.index("--api-key-env") + 1], "ANTHROPIC_API_KEY")
        self.assertNotIn("--effort", argv)   # Evren kataloğuna bağlı bayrak başka hizmette atlanır
        path = os.path.join(self._tmp.name, "key_claude")
        self.assertEqual(Path(path).read_text(), "sk-secret")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_missing_service_key_refuses_spawn(self):
        with self.assertRaises(ValueError):
            self.build({"service": "grok"})

    def test_evren_service_changes_nothing(self):
        self.assertEqual(self.build({"service": "evren"}), self.build(None))

    def test_exec_flags_appended_and_gated_by_binary(self):
        argv = shlex.split(self.build({"exec_cmds": ["cargo"], "exec_own_glob": ["tests/**"], "exec_timeout": 90}))
        tail = argv[argv.index("--allow-exec"):]
        self.assertEqual(tail, ["--allow-exec", "--allow-exec-cmd", "cargo", "--allow-exec-own-glob", "tests/**",
                                "--exec-timeout-secs", "90"])
        ucli_client._HELP_CACHE.clear()
        self.binary = fake_ucli(self._tmp.name, HELP_BOTH, name="old")
        with self.assertRaises(ValueError):     # eski ikili: yarım exec izni YOK
            self.build({"exec_cmds": ["cargo"]})


class WiringTests(unittest.TestCase):
    def test_only_ucli_accepts_cli_opts(self):
        for name in ("claude", "codex", "agy", "shell", "copilot"):
            self.assertFalse(get_provider(name).accepts_cli_opts, name)
            self.assertTrue(get_provider(name).validate_cli_opts({"service": "claude"})[1])
        self.assertTrue(get_provider("ucli").accepts_cli_opts)

    def test_spawn_never_passes_cli_opts_to_other_providers(self):
        prov = get_provider("claude")
        with mock.patch.object(type(prov), "build_inner_command", return_value="claude") as b, \
                mock.patch.object(type(prov), "resolve_resume_id", return_value=None):
            spawn.spawn_session("n", "/tmp", "m", display=":0", cli="claude", dry_run=True, cli_opts={"service": "claude"})
        self.assertNotIn("cli_opts", b.call_args.kwargs)

    def test_start_rejects_opts_for_non_ucli_and_invalid_opts(self):
        from claudeops.commands import web
        info = {"state": "active", "cli": "claude", "model": "m", "cwd": "/tmp"}
        with mock.patch.object(web, "_fleet_status", return_value={"n": info}), \
                mock.patch.object(web, "find_sessions", return_value=[]), \
                mock.patch.object(web, "diag_log", lambda *a, **k: None), \
                mock.patch.object(web, "spawn_session") as sp:
            r = web._start("n", cli_opts={"service": "claude"})
            self.assertFalse(r["ok"])
            r = web._start("n", cli="ucli", model="m", cli_opts={"exec_cmds": ["bash"]})
            self.assertFalse(r["ok"])
            sp.assert_not_called()


if __name__ == "__main__":
    unittest.main()

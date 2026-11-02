"""Değnekçi beyni ucli + Claude hizmeti (Anthropic API) ile: `max_cost_usd` doğrulama/argv, ucli MCP kaydı (`mcp add` argv'si,
`--with-mcp` yalnız ikili tanıyorsa ve kayıt başarılıysa), spawn'ın `cwd`yi yalnız `mcp_needs_cwd` provider'a geçmesi, `brain_start`
(`brain_cli=ucli` -> `cli_opts`; varsayılan claude yolu birebir aynı) ve `brain_service`/`brain_max_cost_usd` ayarları.

GERÇEK spawn/tmux/ağ/API/anahtar YOK: ucli ikilisi yardım metni basan sahte betik, `subprocess.run` sahte, `_Brain` gerçek
`spawn_session`ı sahteler, ayarlar geçici dosyada (gerçek settings.json'un hash'i koşu öncesi/sonrası karşılaştırılır)."""
import hashlib
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claudeops import settings, spawn, steward as sw, ucli_client  # noqa: E402
from claudeops import ucli_session_opts as so  # noqa: E402
from claudeops.commands import mcp_steward, web_steward as ws  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.providers.base import McpServerSpec  # noqa: E402
from test_steward_brain import _Brain  # noqa: E402
from test_ucli_start_opts import HELP_EXEC  # noqa: E402
from test_ucli_web import fake_ucli  # noqa: E402

_REAL_SETTINGS = os.path.expanduser("~/.claude/claudeops/settings.json")
_HASH_BEFORE = None


def _sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def setUpModule():
    global _HASH_BEFORE
    _HASH_BEFORE = _sha(_REAL_SETTINGS)


def tearDownModule():
    if _sha(_REAL_SETTINGS) != _HASH_BEFORE:
        raise AssertionError("gerçek ~/.claude/claudeops/settings.json test sırasında değişti")


HELP_MCP = HELP_EXEC + "      --with-mcp\n      --max-cost-usd <MAX_COST_USD>\n"


class ValidateMaxCostTests(unittest.TestCase):
    def test_valid_values(self):
        self.assertEqual(so.validate_opts({"max_cost_usd": "1.5"}), ({"max_cost_usd": 1.5}, ""))
        self.assertEqual(so.validate_opts({"max_cost_usd": "0,25"}), ({"max_cost_usd": 0.25}, ""))
        self.assertEqual(so.validate_opts({"service": "claude", "max_cost_usd": 1.0}),
                         ({"service": "claude", "max_cost_usd": 1.0}, ""))

    def test_zero_or_empty_drops_the_key(self):
        self.assertEqual(so.validate_opts({"max_cost_usd": 0}), ({}, ""))
        self.assertEqual(so.validate_opts({"max_cost_usd": ""}), ({}, ""))

    def test_invalid_values_rejected(self):
        for v in ("x", -1, "nan", "inf", so.MAX_COST_USD + 1):
            out, err = so.validate_opts({"max_cost_usd": v})
            self.assertTrue(err, v)
            self.assertEqual(out, {})


class _Bin(unittest.TestCase):
    HELP = HELP_MCP

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        ucli_client._HELP_CACHE.clear()
        self.addCleanup(ucli_client._HELP_CACHE.clear)
        self.binary = fake_ucli(self.tmp, self.HELP)
        ucli_client.chat_help_text(self.binary)     # önbelleğe al: testler `subprocess.run`ı (paylaşılan modül) sahteler
        self.logs = []
        for p in (mock.patch.object(up, "resolve_binary", lambda: self.binary),
                  mock.patch.object(up, "diag_log", lambda ev, **k: self.logs.append((ev, k)))):
            p.start()
            self.addCleanup(p.stop)


class MaxCostArgsTests(_Bin):
    def test_priced_model_gets_the_flag_once(self):
        argv = up._max_cost_args([self.binary, "--model", "claude-sonnet-5-5"], 1.0, "b")
        self.assertEqual(argv[-2:], ["--max-cost-usd", "1"])
        self.assertEqual(up._max_cost_args(argv, 2.5)[-2:], ["--max-cost-usd", "2.5"])
        self.assertEqual(up._max_cost_args(argv, 2.5).count("--max-cost-usd"), 1)

    def test_unpriced_model_is_skipped_and_logged(self):
        argv = [self.binary, "--model", "claude-haiku-5-5"]
        self.assertEqual(up._max_cost_args(list(argv), 1.0, "b"), argv)
        self.assertIn("ucli_max_cost_skipped", [e for e, _ in self.logs])

    def test_binary_without_flag_is_skipped(self):
        ucli_client._HELP_CACHE.clear()
        old = fake_ucli(self.tmp, HELP_EXEC, name="old")
        argv = [old, "--model", "claude-sonnet-5-5"]
        self.assertEqual(up._max_cost_args(list(argv), 1.0, "b"), argv)
        self.assertIn(("ucli_flag_unsupported", "--max-cost-usd"), [(e, k.get("flag")) for e, k in self.logs])


class McpRegisterTests(_Bin):
    def spec(self, tools=("steward_overview", "steward_answer")):
        return McpServerSpec(name="cops-steward", command="/repo/py/cops", args=("mcp-steward", "--steward", "kitap"),
                             allowed_tools=tools)

    def test_server_name_follows_ucli_rule(self):
        self.assertEqual(up.mcp_server_name("cops-steward"), "cops_steward")
        self.assertEqual(up.mcp_server_name("x" * 40), "x" * 24)
        self.assertEqual(up.mcp_server_name(""), "mcp")

    def test_add_argv_shape(self):
        argv = up.mcp_add_argv("/b/ucli", "/w", self.spec())
        self.assertEqual(argv, ["/b/ucli", "--root", "/w", "mcp", "add", "cops_steward", "--command", "/repo/py/cops",
                                "--allow-tool", "steward_overview", "--allow-tool", "steward_answer",
                                "--", "mcp-steward", "--steward", "kitap"])

    def test_launch_args_register_then_with_mcp(self):
        os.makedirs(os.path.join(self.tmp, ".ucli"))
        stale = os.path.join(self.tmp, ".ucli", "mcp.json")
        Path(stale).write_text("{}")
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw))
            self.assertFalse(os.path.exists(stale))          # eski kayıt add'den ÖNCE silindi (onayı biz vermeyiz)
            return subprocess.CompletedProcess(argv, 0, "{}", "")
        with mock.patch.object(up.subprocess, "run", run):
            out = up.UcliProvider().mcp_launch_args(self.spec(), cwd=self.tmp)
        self.assertEqual(out, ["--with-mcp"])
        self.assertEqual(len(calls), 1)
        argv, kw = calls[0]
        self.assertEqual(argv[:6], [self.binary, "--root", self.tmp, "mcp", "add", "cops_steward"])
        self.assertNotIn("trust", argv)
        self.assertIs(kw["stdin"], subprocess.DEVNULL)
        self.assertIn("timeout", kw)

    def test_failed_add_means_no_with_mcp(self):
        with mock.patch.object(up.subprocess, "run",
                               lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "Server already exists")):
            self.assertEqual(up.UcliProvider().mcp_launch_args(self.spec(), cwd=self.tmp), [])
        self.assertIn("ucli_mcp_register_failed", [e for e, _ in self.logs])
        with mock.patch.object(up.subprocess, "run", mock.Mock(side_effect=subprocess.TimeoutExpired("x", 1))):
            self.assertEqual(up.UcliProvider().mcp_launch_args(self.spec(), cwd=self.tmp), [])

    def test_nothing_runs_without_tools_workspace_or_flag(self):
        old = fake_ucli(self.tmp, HELP_EXEC, name="old")
        ucli_client.chat_help_text(old)
        run = mock.Mock()
        with mock.patch.object(up.subprocess, "run", run):
            self.assertEqual(up.UcliProvider().mcp_launch_args(self.spec(tools=()), cwd=self.tmp), [])
            self.assertEqual(up.UcliProvider().mcp_launch_args(self.spec(tools=("bad name;",)), cwd=self.tmp), [])
            self.assertEqual(up.UcliProvider().mcp_launch_args(self.spec(), cwd=""), [])
            self.assertEqual(up.UcliProvider().mcp_launch_args(self.spec(), cwd="rel/dir"), [])
            self.binary = old
            self.assertEqual(up.UcliProvider().mcp_launch_args(self.spec(), cwd=self.tmp), [])
        run.assert_not_called()

    def test_symlinked_state_dir_is_refused(self):
        target = os.path.join(self.tmp, "elsewhere")
        os.makedirs(target)
        ws_dir = os.path.join(self.tmp, "ws")
        os.makedirs(ws_dir)
        os.symlink(target, os.path.join(ws_dir, ".ucli"))
        run = mock.Mock()
        with mock.patch.object(up.subprocess, "run", run):
            self.assertEqual(up.UcliProvider().mcp_launch_args(self.spec(), cwd=ws_dir), [])
        run.assert_not_called()

    def test_steward_spec_allowlists_exactly_the_steward_tools(self):
        spec = mcp_steward.default_spec("kitap")
        self.assertEqual(tuple(spec.allowed_tools), tuple(t["name"] for t in mcp_steward.TOOLS))
        self.assertTrue(spec.allowed_tools and all(t.startswith("steward_") for t in spec.allowed_tools))
        self.assertEqual(tuple(mcp_steward.default_spec().args), ("mcp-steward",))


class BuildWithMcpTests(_Bin):
    def setUp(self):
        super().setUp()
        self.keys = {}
        for p in (mock.patch.object(up, "_sync_api_key_file", lambda: False),
                  mock.patch.object(up, "ucli_limit_overrides", lambda: {}),
                  mock.patch.object(up, "byok_env_for", lambda cli: dict(self.keys)),
                  mock.patch.object(up, "_service_key_file", lambda s: os.path.join(self.tmp, f"key_{s}")),
                  mock.patch.object(up, "_web_args", lambda *a, **k: []),
                  mock.patch.object(up, "_script_args", lambda *a, **k: []),
                  mock.patch.object(up, "_stream_args", lambda *a, **k: []),
                  mock.patch.object(up, "_state_dir_args", lambda *a, **k: []),
                  mock.patch.object(up, "_effort_args", lambda *a, **k: []),
                  mock.patch.object(up.ucli_cost, "cap_exceeded", lambda: False)):
            p.start()
            self.addCleanup(p.stop)

    def build(self, extra=(), opts=None, model="claude-sonnet-5-5"):
        return up.UcliProvider().build_inner_command("/w", model, "read-only", "high", None, "", "degnekci",
                                                     extra_args=extra, cli_opts=opts)

    def test_only_with_mcp_is_taken_from_extra_args(self):
        argv = shlex.split(self.build(extra=["--with-mcp", "--mcp-config", "/x"]))
        self.assertEqual(argv.count("--with-mcp"), 1)
        self.assertNotIn("--mcp-config", argv)
        self.assertNotIn("--with-mcp", shlex.split(self.build()))

    def test_claude_service_with_cost_cap_and_mcp(self):
        self.keys = {"ANTHROPIC_API_KEY": "sk-secret"}
        cmd = self.build(extra=["--with-mcp"], opts={"service": "claude", "max_cost_usd": 1.0})
        self.assertNotIn("sk-secret", cmd)
        argv = shlex.split(shlex.split(cmd)[2].split(" exec ", 1)[1])
        self.assertEqual(argv[argv.index("--max-cost-usd") + 1], "1")
        self.assertEqual(argv[argv.index("--provider") + 1], "anthropic-messages")
        self.assertIn("--with-mcp", argv)
        self.assertNotIn("--allow-edit", argv)          # beyin salt-okunur (yalnız MCP araçlarıyla iş görür)


class SpawnCwdWiringTests(unittest.TestCase):
    class _Prov:
        accepts_cli_opts = False

        def __init__(self, needs):
            self.mcp_needs_cwd = needs
            self.seen = []

        def resolve_resume_id(self, cwd, in_use=frozenset(), session_name=""):
            return None

        def resolve_effort(self, model, effort):
            return effort

        def mcp_launch_args(self, spec, **kw):
            self.seen.append(kw)
            return []

        def build_inner_command(self, *a, **k):
            return "true"

        def env_overrides(self, name):
            return {}

    def test_cwd_only_for_providers_that_ask(self):
        spec = McpServerSpec(name="s", command="c")
        for needs, want in ((True, [{"cwd": "/w"}]), (False, [{}])):
            prov = self._Prov(needs)
            with mock.patch.object(spawn, "get_provider", lambda cli: prov), \
                    mock.patch.object(spawn, "_ids_held_by_others", lambda name: frozenset()):
                out = spawn.spawn_session(name="n", cwd="/w", model="m", display=":0", dry_run=True, mcp_server=spec)
            self.assertTrue(out.startswith("[dry-run]"))
            self.assertEqual(prov.seen, want)


class BrainUcliTests(_Brain):
    def test_default_claude_brain_passes_no_cli_opts(self):
        self.settings()
        self.assertTrue(ws.brain_start()["ok"])
        kw = self.spawns[0]
        self.assertEqual(kw["cli"], "claude")
        self.assertNotIn("cli_opts", kw)                      # eski çağrı birebir

    def test_ucli_brain_uses_claude_service_and_cost_cap(self):
        self.settings(default={"brain_cli": "ucli", "brain_model": ""})
        res = ws.brain_start()
        self.assertTrue(res["ok"], res)
        kw = self.spawns[0]
        self.assertEqual(kw["cli"], "ucli")
        self.assertEqual(kw["cli_opts"], {"service": "claude", "max_cost_usd": 1.0})
        self.assertEqual(kw["model"], "claude-sonnet-5-5")    # Claude hizmetinin ilk modeli (Evren kataloğu değil)
        self.assertEqual(kw["permission_mode"], "read-only")
        self.assertEqual(tuple(kw["mcp_server"].allowed_tools), tuple(t["name"] for t in mcp_steward.TOOLS))
        self.assertEqual(self.records[0][1]["cli"], "ucli")

    def test_settings_override_service_model_and_cap(self):
        self.settings(kitap={"enabled": "on", "brain_cli": "ucli", "brain_model": "claude-opus-5-5",
                             "brain_service": "Claude", "brain_max_cost_usd": "0"})
        cfg = settings.steward_config("kitap")
        self.assertEqual((cfg.brain_service, cfg.brain_max_cost_usd), ("Claude", 0.0))
        self.assertTrue(ws.brain_start(cfg)["ok"])
        kw = self.spawns[0]
        self.assertEqual((kw["model"], kw["cli_opts"]), ("claude-opus-5-5", {"service": "claude"}))

    def test_defaults(self):
        self.settings()
        cfg = settings.steward_config()
        self.assertEqual((cfg.brain_cli, cfg.brain_service, cfg.brain_max_cost_usd), ("claude", "claude", 1.0))
        self.assertNotIn("brain_service", sw.MACHINE_KEYS)
        self.assertNotIn("brain_max_cost_usd", sw.MACHINE_KEYS)

    def test_unknown_service_refuses_without_spawn(self):
        self.settings(default={"brain_cli": "ucli", "brain_service": "nope"})
        res = ws.brain_start()
        self.assertFalse(res["ok"])
        self.assertEqual((self.spawns, self.records), ([], []))
        self.assertIn("brain_start_refused", [e["event"] for e in sw.tail_log(10)])

    def test_spawn_refusal_is_reported_not_raised(self):
        self.settings(default={"brain_cli": "ucli"})
        with mock.patch.object(ws, "spawn_session", mock.Mock(side_effect=ValueError("claude: anahtar yok"))):
            res = ws.brain_start()
        self.assertEqual(res, {"ok": False, "error": "claude: anahtar yok"})

    def test_claude_brain_value_error_still_raises(self):
        self.settings()
        with mock.patch.object(ws, "spawn_session", mock.Mock(side_effect=ValueError("x"))):
            with self.assertRaises(ValueError):
                ws.brain_start()


if __name__ == "__main__":
    unittest.main()

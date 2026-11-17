"""K13: register_mcp_server + `cops mcp-ext` (stdio JSON-RPC, eklenti handler'ı aynı süreçte)."""
import io
import json
import sys
import unittest
from unittest import mock

from claudeops import extensions
from claudeops.commands import mcp_ext

TOOLS = [{"name": "demo_echo", "description": "d", "inputSchema": {"type": "object", "properties": {}, "required": []}}]


class McpHook(unittest.TestCase):
    def setUp(self):
        self._saved = dict(extensions._MCP)

    def tearDown(self):
        extensions._MCP.clear()
        extensions._MCP.update(self._saved)

    def test_validation(self):
        api = extensions.ExtensionAPI()
        with self.assertRaises(ValueError):
            api.register_mcp_server("bad id!", TOOLS, lambda n, a: {})
        with self.assertRaises(ValueError):
            api.register_mcp_server("demo", [{"name": "steward_x", "inputSchema": {}}], lambda n, a: {})   # önek çakışması
        with self.assertRaises(ValueError):
            api.register_mcp_server("demo", [{"name": "demo_x"}], lambda n, a: {})                          # inputSchema yok
        api.register_mcp_server("demo", TOOLS, lambda n, a: {"ok": True})
        api.register_mcp_server("demo", TOOLS, lambda n, a: {"ok": True})                                   # idempotent
        self.assertIn("demo", extensions.mcp_servers())

    def test_stdio_roundtrip(self):
        extensions.ExtensionAPI().register_mcp_server("demo", TOOLS, lambda n, a: {"ok": True, "tool": n, "got": a})
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "demo_echo", "arguments": {"x": 1}}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope", "arguments": {}}}]
        out = io.StringIO()
        with mock.patch.object(extensions, "load", return_value={}), \
                mock.patch.object(sys, "stdin", io.StringIO("\n".join(json.dumps(m) for m in msgs) + "\n")), \
                mock.patch.object(sys, "stdout", out):
            rc = mcp_ext.run(type("A", (), {"server_id": "demo"})())
        self.assertEqual(rc, 0)
        replies = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
        self.assertEqual(replies[0]["result"]["tools"][0]["name"], "demo_echo")
        body = json.loads(replies[1]["result"]["content"][0]["text"])
        self.assertEqual(body["got"], {"x": 1})
        self.assertTrue(replies[2]["result"]["isError"])

    def test_unknown_server_exit_2(self):
        with mock.patch.object(extensions, "load", return_value={}):
            self.assertEqual(mcp_ext.run(type("A", (), {"server_id": "yok"})()), 2)


if __name__ == "__main__":
    unittest.main()


class SessionAttach(unittest.TestCase):
    def setUp(self):
        self._m, self._s = dict(extensions._MCP), dict(extensions._SESSION_MCP)

    def tearDown(self):
        extensions._MCP.clear(); extensions._MCP.update(self._m)
        extensions._SESSION_MCP.clear(); extensions._SESSION_MCP.update(self._s)

    def test_attach_predicate_and_spec(self):
        api = extensions.ExtensionAPI()
        with self.assertRaises(ValueError):
            api.attach_mcp_to_sessions("demo", lambda c: True)       # kayıtsız kimlik
        api.register_mcp_server("demo", TOOLS, lambda n, a: {"ok": True})
        api.attach_mcp_to_sessions("demo", lambda c: c == "/p/migrated")
        self.assertIsNone(extensions.session_mcp_spec("/p/other"))
        sp = extensions.session_mcp_spec("/p/migrated")
        self.assertEqual(list(sp.args), ["mcp-ext", "demo"])
        self.assertEqual(sp.name, "cops-ext-demo")
        self.assertEqual(list(sp.allowed_tools), ["demo_echo"])
        api.attach_mcp_to_sessions("demo", lambda c: 1 / 0)           # hata -> bağlanmaz, istisna sızmaz
        self.assertIsNone(extensions.session_mcp_spec("/p/migrated"))

    def test_claude_config_path_per_ext_and_spawn_wiring(self):
        from claudeops.providers import claude_provider as cp
        from claudeops.providers.base import McpServerSpec
        a = cp._mcp_config_path(McpServerSpec(name="x", command="c", args=("mcp-ext", "notes")))
        self.assertTrue(a.endswith("mcp_config_ext_notes.json"))
        self.assertTrue(cp._mcp_config_path(McpServerSpec(name="q", command="c", args=("mcp-queue",))).endswith("mcp_config.json"))

    def test_spawn_attaches_only_matching_cwd_and_claude(self):
        from claudeops import spawn
        from claudeops.providers import claude_provider as cp
        api = extensions.ExtensionAPI()
        api.register_mcp_server("demo", TOOLS, lambda n, a: {"ok": True})
        api.attach_mcp_to_sessions("demo", lambda c: c == "/tmp")
        seen = []

        def spy(self, spec):
            seen.append(spec.name)
            return []
        with mock.patch.object(cp.ClaudeProvider, "mcp_launch_args", spy):
            spawn.spawn_session(name="zz_t", cwd="/tmp", model="claude-sonnet-5-5", dry_run=True, cli="claude")
            spawn.spawn_session(name="zz_t", cwd="/home", model="claude-sonnet-5-5", dry_run=True, cli="claude")
            spawn.spawn_session(name="zz_t", cwd="/tmp", model="m", dry_run=True, cli="codex")
        self.assertEqual(seen, ["cops-ext-demo"])

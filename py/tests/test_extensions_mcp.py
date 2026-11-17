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

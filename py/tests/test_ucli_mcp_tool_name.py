"""TBD#373 (5): MCP araç adı sonunda satır sonu ile kabul EDİLMEZ (`$` yerine tam eşleşme)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.providers.base import McpServerSpec  # noqa: E402


class McpToolNameTest(unittest.TestCase):
    def _launch(self, tools):
        spec = McpServerSpec(name="s", command="c", args=(), allowed_tools=tuple(tools))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(up, "resolve_binary", return_value="ucli"), \
                mock.patch.object(up, "binary_supports_flag", return_value=True), \
                mock.patch.object(up, "register_mcp", return_value=True) as reg, mock.patch.object(up, "diag_log"):
            out = up.UcliProvider().mcp_launch_args(spec, cwd=d)
        return out, (reg.call_args.args[2].allowed_tools if reg.called else None)

    def test_trailing_newline_name_is_dropped(self):
        self.assertEqual(self._launch(["ok", "kotu\n"]), (["--with-mcp"], ("ok",)))

    def test_only_bad_names_means_no_mcp(self):
        self.assertEqual(self._launch(["kotu\n", "a\nb", "x" * 64 + "\n"]), ([], None))


if __name__ == "__main__":
    unittest.main()

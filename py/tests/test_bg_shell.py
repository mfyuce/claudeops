import unittest
from unittest import mock

from claudeops.commands import web_steward as ws


class _Child:
    def __init__(self, name, cmd):
        self._n, self._c = name, cmd

    def name(self):
        return self._n

    def cmdline(self):
        return self._c


class BgShellTests(unittest.TestCase):
    def _run(self, kids):
        proc = mock.Mock()
        proc.children.return_value = kids
        with mock.patch.object(ws.psutil, "Process", return_value=proc):
            return ws.bg_shell_running(1)

    def test_tool_shell_child_counts(self):
        self.assertTrue(self._run([_Child("bash", ["/bin/bash", "-c", "source /h/.claude/shell-snapshots/s.sh && sleep 999"])]))

    def test_mcp_server_and_plain_shell_do_not(self):
        self.assertFalse(self._run([_Child("node", ["node", "mcp.js"]), _Child("bash", ["/bin/bash", "-i"])]))

    def test_no_children_or_error(self):
        self.assertFalse(self._run([]))
        with mock.patch.object(ws.psutil, "Process", side_effect=ws.psutil.NoSuchProcess(1)):
            self.assertFalse(ws.bg_shell_running(1))


if __name__ == "__main__":
    unittest.main()

import types
import unittest
from unittest import mock

from claudeops.commands import web_steward as ws


class _Child:
    def __init__(self, name, cmd, created=None):
        self._n, self._c, self._t = name, cmd, created

    def create_time(self):
        if self._t is None:
            raise ws.psutil.AccessDenied(1)
        return self._t

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


class LongBgShellTests(unittest.TestCase):
    """26 Kas pid 305171: koşulu hiç gelmeyen bekleme döngüsü oturumu saatlerce meşgul gösterdi; motor komutu ve yaşı söylesin."""
    LOOP = ["/bin/bash", "-c", "source /h/.claude/shell-snapshots/s.sh && eval 'until tail -1 f | grep -q load; do sleep 5; done'"]

    def _shells(self, kids, now=10_000.0):
        proc = mock.Mock()
        proc.children.return_value = kids
        with mock.patch.object(ws.psutil, "Process", return_value=proc):
            return ws.bg_shells(1, now=now)

    def test_command_after_eval_and_age(self):
        self.assertEqual(self._shells([_Child("bash", self.LOOP, created=4_000.0)]),
                         [("until tail -1 f | grep -q load; do sleep 5; done", 6_000.0)])

    def test_unreadable_age_is_zero(self):
        self.assertEqual(self._shells([_Child("bash", self.LOOP)])[0][1], 0.0)

    def test_long_only_above_threshold(self):
        sess = [types.SimpleNamespace(name="a", pid=1), types.SimpleNamespace(name="b", pid=0)]
        with mock.patch.object(ws, "bg_shells", lambda pid: [("sleep 1", 60.0), ("loop", 7200.0)]):
            self.assertEqual(ws.long_bg_shells(sess), [("a", "loop", 7200.0)])


if __name__ == "__main__":
    unittest.main()

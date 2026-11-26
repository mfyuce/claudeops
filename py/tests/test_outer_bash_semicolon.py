"""`;` ile biten adda spawn parçası `-s 'ad\;'` yazar; yedek süreç taraması iğnesini aynı kaçışla kurmazsa pencereyi
bulamaz."""
import shlex
import unittest
from unittest import mock

from claudeops import tmux_backend as tb


class _Proc:
    def __init__(self, pid, script):
        self.pid = pid
        self.info = {"name": "bash", "uids": mock.Mock(real=__import__("os").getuid())}
        self._cmd = ["bash", "-c", script]

    def cmdline(self):
        return self._cmd

    def create_time(self):
        return 1.0


class SemicolonNeedleTests(unittest.TestCase):
    def test_window_opened_by_the_current_fragment_is_found(self):
        for name in ["semi;", "duz", "bos luk;"]:
            script = tb.tmux_new_session_shell_fragment(name, "/tmp", "sleep 1") + "; exec bash"
            with mock.patch.object(tb, "_outer_bash_via_list_clients", lambda n: []), \
                    mock.patch("psutil.process_iter", lambda attrs: [_Proc(7, script), _Proc(8, "echo " + shlex.quote("x"))]):
                self.assertEqual(tb.find_outer_bash_pids(name), [(7, 1.0)], name)


if __name__ == "__main__":
    unittest.main()

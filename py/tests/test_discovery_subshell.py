"""Düz shell alt kabuğu ikinci oturum satırı üretmez (yuhem'de aynı adlı iki `shell_yuhem*` satırı)."""
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops import discovery                     # noqa: E402
from claudeops.session import Session               # noqa: E402


def _s(name, pid, cli="shell"):
    return Session(name=name, pid=pid, cwd="/x", sid=None, model=None, permission_mode=None, effort=None,
                   cpu=0.0, cli=cli)


class FoldSubshellTests(unittest.TestCase):
    def test_descendants_drop_independent_and_other_cli_stay(self):
        tree = {11: [10], 12: [99, 11, 10], 21: [20], 30: []}
        rows = [_s("a", 10), _s("a", 11), _s("a", 12), _s("a", 30), _s("b", 21),
                _s("c", 40, "claude"), _s("c", 41, "claude")]
        out = discovery.fold_subshells(rows, lambda pid: tree.get(pid, [40]))
        self.assertEqual([s.pid for s in out], [10, 30, 21, 40, 41])


@unittest.skipUnless(shutil.which("bash") and os.path.isdir("/proc"), "linux + bash")
class RealSubshellTests(unittest.TestCase):
    def test_background_subshell_is_one_session(self):
        name = f"zz_subshell_test_{os.getpid()}"
        p = subprocess.Popen(["bash", "-c", "exec -a claudeops-shell bash -c '( sleep 30; true ) & wait'"],
                             env=dict(os.environ, COPS_NAME=name), start_new_session=True)

        def stop():
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        self.addCleanup(stop)

        def shells():       # alt kabuk gerçekten doğana dek bekle (yoksa test boşa geçer)
            return [c for c in discovery.psutil.Process(p.pid).children()
                    if c.cmdline()[:1] == ["claudeops-shell"]]
        deadline = time.time() + 10
        while not shells() and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(shells())
        found = [s.pid for s in discovery.find_sessions(measure_cpu=False) if s.name == name]
        self.assertEqual(found, [p.pid])


if __name__ == "__main__":
    unittest.main()

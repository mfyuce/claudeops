"""`UcliReplSession`: stderr sürekli boşaltılır (dolu boru ucli'yi bloklayıp cevabı kilitlemesin); ölünce son stderr iletiye girer."""
import os
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import ucli_client as uc  # noqa: E402


def _fake(code: str) -> str:
    d = tempfile.mkdtemp()
    p = os.path.join(d, "fake.py")
    open(p, "w").write(textwrap.dedent(code))
    return p


class StderrDrain(unittest.TestCase):
    def _session(self, script):
        argv = [sys.executable, script]
        with mock.patch.object(uc, "build_chat_argv", lambda *a, **k: argv), mock.patch.object(uc, "resolve_binary", lambda b=None: "x"):
            return uc.UcliReplSession("/tmp")

    def test_large_stderr_does_not_deadlock(self):
        s = self._session(_fake('''
            import sys
            sys.stdin.readline()
            sys.stderr.write("e" * 300000 + "\\n"); sys.stderr.flush()     # boru (64 KiB) dolardı
            print('{"reply": "ok"}', flush=True)
            sys.stdin.readline()
        '''))
        self.addCleanup(s.close)
        self.assertEqual(s.ask("hi", timeout=10)["reply"], "ok")

    def test_death_reports_stderr_tail(self):
        s = self._session(_fake('''
            import sys
            sys.stdin.readline()
            sys.stderr.write("boom-sebebi\\n")
        '''))
        with self.assertRaises(uc.UcliError) as cm:
            s.ask("hi", timeout=10)
        self.assertIn("boom-sebebi", str(cm.exception))

    def test_tail_is_bounded(self):
        s = self._session(_fake('''
            import sys
            sys.stdin.readline()
            for i in range(5000): sys.stderr.write("satir%05d " % i + "x" * 100 + "\\n")
            sys.stderr.flush()
        '''))
        with self.assertRaises(uc.UcliError) as cm:
            s.ask("hi", timeout=10)
        msg = str(cm.exception)
        self.assertLess(len(msg), 40000)
        self.assertIn("satir04999", msg)


if __name__ == "__main__":
    unittest.main()

"""tmux_send_keys: tek satırlık metnin sonundaki `;` tmux'ta komut ayıracı sayılıp kayboluyordu (review uzops R-4, 17 Kas);
tmux_send_raw'daki kaçış tek satır yolunda yoktu."""
import os
from _tmux_sock import unlink_socket  # noqa: E402
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from claudeops import tmux_backend as tb


class SendKeysSemicolonArgv(unittest.TestCase):
    def sent(self, text):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0)
        with mock.patch.object(tb.subprocess, "run", run):
            self.assertTrue(tb.tmux_send_keys("x", text))
        return [c[-1] for c in calls if "-l" in c]

    def test_trailing_semicolon_escaped(self):
        self.assertEqual(self.sent("foo;"), ["foo\;"])
        self.assertEqual(self.sent("a;b"), ["a;b"])
        self.assertEqual(self.sent("tamam"), ["tamam"])


@unittest.skipUnless(subprocess.run(["which", "tmux"], capture_output=True).returncode == 0, "tmux yok")
class RealTmux(unittest.TestCase):
    def test_literal_roundtrip(self):
        d = tempfile.mkdtemp()
        out = os.path.join(d, "o")
        sock = "cxsk%d" % os.getpid()
        base = ["tmux", "-L", sock, "-f", "/dev/null"]
        subprocess.run(base + ["new-session", "-d", "-s", "t", f"cat > {out}"], check=True)
        try:
            with mock.patch.object(tb, "_base_argv", lambda: ["tmux", "-L", sock]), mock.patch.object(tb, "_exact", lambda n: "t"):
                self.assertTrue(tb.tmux_send_keys("t", "foo;"))
                self.assertTrue(tb.tmux_send_keys("t", "x;y;"))
            subprocess.run(base + ["send-keys", "-t", "t", "C-d"])
            time.sleep(0.5)
            self.assertEqual(open(out).read().split("\n")[:2], ["foo;", "x;y;"])
        finally:
            subprocess.run(base + ["kill-server"], capture_output=True)
            unlink_socket(sock)


if __name__ == "__main__":
    unittest.main()

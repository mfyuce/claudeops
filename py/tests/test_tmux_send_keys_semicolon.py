"""tmux_send_keys: tek satırlık metnin sonundaki `;` pane'e aynen ulaşır (review uzops R-4, 17 Kas). Metin artık argv'ye
girmediği için (tampon yolu, TBD#369) kaçış gerekmez."""
import os
from _tmux_sock import unlink_socket  # noqa: E402
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from claudeops import tmux_backend as tb


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

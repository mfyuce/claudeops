"""TBD#385 (a): canlı yazma kipinin ham tuş verisi (parola dahil) tmux argv'sine GİRMEZ; stdin'den tampona yüklenip
`paste-buffer -r` ile olduğu gibi yazılır. tmux 3.7+ kontrol karakterlerini `-S` verilmezse görünür metne çevirir."""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from claudeops import tmux_backend as tb
from _tmux_sock import unlink_socket  # noqa: E402

OLD_USAGE = "paste-buffer (pasteb) [-dpr] [-s separator] [-b buffer-name] [-t target-pane]\n"
NEW_USAGE = "paste-buffer (pasteb) [-dprS] [-s separator] [-b buffer-name] [-t target-pane]\n"


class Fake:
    def __init__(self, usage=OLD_USAGE, paste_rc=0, probe_rc=0, hang=False):
        self.usage, self.paste_rc, self.probe_rc, self.hang = usage, paste_rc, probe_rc, hang
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw.get("input")))
        if "list-commands" in argv:
            return mock.Mock(returncode=self.probe_rc, stdout=("send-keys (send) [-FHlMRX]\n" + self.usage).encode())
        if "load-buffer" in argv:
            if self.hang:
                raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
            return mock.Mock(returncode=self.paste_rc, stdout=b"")
        return mock.Mock(returncode=0, stdout=b"")

    def named(self, sub):
        return [c for c in self.calls if sub in c[0]]


class RawViaStdin(unittest.TestCase):
    def setUp(self):
        tb._reset_raw_paste_probe()
        self.addCleanup(tb._reset_raw_paste_probe)

    def send(self, data, fake=None, **kw):
        fake = fake or Fake()
        with mock.patch.object(tb.subprocess, "run", fake):
            return tb.tmux_send_raw("x", data, **kw), fake

    def test_data_goes_through_stdin_never_argv(self):
        for data in ("gizli-parola", "\r", "\x1b[A", "\x03", "\t", "\x7f", "foo;", ";", "-", "a\x00b", "\x00", "şğ" * 4000):
            ok, f = self.send(data)
            self.assertTrue(ok, repr(data[:20]))
            (argv, sent), = f.named("load-buffer")
            self.assertEqual(sent, data.encode("utf-8"))
            self.assertFalse(f.named("send-keys"))
            if len(data) > 3:
                self.assertFalse(any(data[:6] in a for c, _ in f.calls for a in c))

    def test_one_process_raw_paste_without_bracket_or_enter(self):
        ok, f = self.send("abc")
        (argv, _), = f.named("load-buffer")
        buf = argv[argv.index("-b") + 1]
        self.assertEqual(argv[argv.index("load-buffer"):],
                         ["load-buffer", "-b", buf, "-", ";", "paste-buffer", "-r", "-d", "-b", buf, "-t", "=x:"])
        self.assertEqual(len(f.calls), 2)          # sürüm yoklaması + tek gönderim süreci

    def test_new_tmux_gets_no_sanitize_flag(self):
        ok, f = self.send("\x1b", Fake(usage=NEW_USAGE))
        (argv, _), = f.named("load-buffer")
        tail = argv[argv.index("paste-buffer"):]
        self.assertEqual(tail[:4], ["paste-buffer", "-r", "-S", "-d"])

    def test_probe_is_cached_then_expires(self):
        f = Fake()
        clock = [100.0]
        with mock.patch.object(tb.time, "monotonic", lambda: clock[0]):
            self.send("a", f)
            self.send("b", f)
            self.assertEqual(len(f.named("list-commands")), 1)
            clock[0] += tb._RAW_PROBE_TTL + 1
            self.send("c", f)
        self.assertEqual(len(f.named("list-commands")), 2)

    def test_failed_probe_sends_nothing(self):
        for fake in (Fake(probe_rc=1), Fake(usage="")):
            tb._reset_raw_paste_probe()
            ok, f = self.send("a", fake)
            self.assertFalse(ok)
            self.assertFalse(f.named("load-buffer"))

    def test_failure_and_timeout_delete_the_buffer_and_reprobe(self):
        for fake in (Fake(paste_rc=1), Fake(hang=True)):
            tb._reset_raw_paste_probe()
            ok, f = self.send("gizli", fake)
            self.assertFalse(ok)
            (load, _), = f.named("load-buffer")
            (drop, _), = f.named("delete-buffer")
            self.assertEqual(drop[-1], load[load.index("-b") + 1])
            self.send("y", f)
            self.assertEqual(len(f.named("list-commands")), 2)

    def test_empty_is_a_no_op(self):
        ok, f = self.send("")
        self.assertTrue(ok)
        self.assertEqual(f.calls, [])

    def test_unencodable_text_sends_nothing(self):
        ok, f = self.send("a\ud800")
        self.assertFalse(ok)
        self.assertFalse(f.named("load-buffer"))


@unittest.skipUnless(shutil.which("tmux"), "tmux yok")
class RealTmux(unittest.TestCase):
    def setUp(self):
        tb._reset_raw_paste_probe()
        self.addCleanup(tb._reset_raw_paste_probe)

    def test_bytes_arrive_untouched_and_no_buffer_remains(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        out = os.path.join(d, "o")
        sock = "cxraw%d" % os.getpid()
        base = ["tmux", "-L", sock, "-f", "/dev/null"]
        reader = os.path.join(d, "r.py")
        with open(reader, "w") as fh:
            fh.write("import os,sys,tty\ntty.setraw(0)\nf=open(sys.argv[1],'wb',0)\n"
                     "while True:\n    f.write(os.read(0,65536))\n")
        subprocess.run(base + ["new-session", "-d", "-s", "t", "python3 -I %s %s" % (reader, out)], check=True)
        try:
            deadline = time.time() + 10
            while not os.path.exists(out) and time.time() < deadline:
                time.sleep(0.05)
            data = "".join(map(chr, range(128))) + "şğüİ€ \x1b[A\x1b[200~x\x1b[201~ foo; bar\\; \r\n#{pane_pid};" + "z;" * 3000
            want = data.encode("utf-8")
            with mock.patch.object(tb, "_base_argv", lambda: ["tmux", "-L", sock]):
                self.assertTrue(tb.tmux_send_raw("t", data))
                self.assertFalse(tb.tmux_send_raw("yok", "gizli"))
            while os.path.getsize(out) < len(want) and time.time() < deadline:
                time.sleep(0.05)
            with open(out, "rb") as fh:
                self.assertEqual(fh.read(), want)
            left = subprocess.run(base + ["list-buffers"], capture_output=True).stdout
            self.assertEqual(left, b"")
        finally:
            subprocess.run(base + ["kill-server"], capture_output=True)
            unlink_socket(sock)


if __name__ == "__main__":
    unittest.main()

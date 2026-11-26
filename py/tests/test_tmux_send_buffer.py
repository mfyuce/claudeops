"""TBD#369: gönderilen metin tmux argv'sine girmez (her metin stdin + tampon); yapıştırma olmazsa (hata, zaman aşımı)
tampon silinir."""
import subprocess
import unittest
from unittest import mock

from claudeops import tmux_backend as tb
from _tmux_iso import HAVE_TMUX, IsoTmux

SECRET = "gizli-parola-123"


class ArgvTests(unittest.TestCase):
    def run_send(self, text, fail_at=None, how="rc"):
        calls = []

        def fake(argv, **kw):
            calls.append((argv, kw.get("input")))
            if fail_at and fail_at in argv:
                if how == "timeout":
                    raise subprocess.TimeoutExpired(argv, 1)
                return mock.Mock(returncode=1)
            return mock.Mock(returncode=0)

        with mock.patch.object(tb.subprocess, "run", fake), mock.patch.object(tb.time, "sleep", lambda s: None), \
                mock.patch.object(tb, "pane_is_masked_input", lambda n: False):
            ok = tb.tmux_send_keys("k", text)
        return ok, calls

    def verbs(self, calls):
        return [next(a for a in argv if a in ("load-buffer", "paste-buffer", "delete-buffer", "send-keys", "display-message"))
                for argv, _ in calls]

    def test_single_line_goes_through_stdin_never_argv(self):
        for text in [SECRET, "-" + SECRET, SECRET + ";", SECRET + "\nikinci"]:
            ok, calls = self.run_send(text)
            self.assertTrue(ok)
            self.assertFalse(any(SECRET in a for argv, _ in calls for a in argv), text)
            self.assertIn(text.encode(), [i for _, i in calls])
            self.assertEqual(self.verbs(calls)[-3:], ["load-buffer", "paste-buffer", "send-keys"])
            self.assertEqual(calls[-1][0][-1], "Enter")

    def test_buffer_deleted_on_every_failure_and_timeout(self):
        for step in ("load-buffer", "paste-buffer"):
            for how in ("rc", "timeout"):
                ok, calls = self.run_send(SECRET, fail_at=step, how=how)
                self.assertFalse(ok)
                self.assertEqual(self.verbs(calls)[-1], "delete-buffer", f"{step} {how}")
                buf = calls[-1][0][-1]
                self.assertTrue(any(buf in argv for argv, _ in calls[:-1]))

    def test_empty_text_only_presses_enter(self):
        ok, calls = self.run_send("")
        self.assertTrue(ok)
        self.assertNotIn("load-buffer", self.verbs(calls))
        self.assertEqual(calls[-1][0][-1], "Enter")


@unittest.skipUnless(HAVE_TMUX, "tmux yok")
class RealTmuxSendTests(unittest.TestCase):
    def test_text_arrives_unchanged_and_no_buffer_remains(self):
        with IsoTmux() as iso:
            out = iso.dir + "/girdi"
            iso.spawn("k", f"exec cat > {out}")
            texts = ["düz metin", "-tire ile", "noktalı virgül;", "bar\\;", "#{pane_tty} #(false)", "iki\nsatır"]
            for text in texts:
                iso.wait(lambda: tb.pane_is_masked_input("k") is False, "pane hazır")
                self.assertTrue(tb.tmux_send_keys("k", text), text)
            want = "".join(t + "\n" for t in texts)
            iso.wait(lambda: open(out, encoding="utf-8").read() == want, "metin aynen ulaşsın")
            self.assertEqual(iso.raw("list-buffers", check=False), "")


if __name__ == "__main__":
    unittest.main()

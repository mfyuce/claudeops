"""tmux_send_raw: `;` ile biten parça tmux'ta komut ayıracı sayılıyordu (sondaki `;` kayboluyordu, review cliops R-1)."""
import subprocess
import unittest
from unittest import mock

from claudeops import tmux_backend as tb


class SemicolonArgv(unittest.TestCase):
    def sent(self, data):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0)
        with mock.patch.object(tb.subprocess, "run", run):
            self.assertTrue(tb.tmux_send_raw("x", data))
        return [c[-1] for c in calls]

    def test_trailing_semicolon_escaped(self):
        self.assertEqual(self.sent("foo;"), ["foo\;"])
        self.assertEqual(self.sent("bar\;"), ["bar\\\;"])       # kullanıcının ters-bölüsü korunur
        self.assertEqual(self.sent("a;b"), ["a;b"])               # ortadaki `;` dokunulmaz

    def test_whole_semicolon_chunk(self):
        self.assertEqual(self.sent(";"), ["\;"])


@unittest.skipUnless(subprocess.run(["which", "tmux"], capture_output=True).returncode == 0, "tmux yok")
class RealTmux(unittest.TestCase):
    def test_literal_roundtrip(self):
        import os, tempfile, time
        d = tempfile.mkdtemp()
        out = os.path.join(d, "o")
        sock = "cxsemi%d" % os.getpid()
        base = ["tmux", "-L", sock, "-f", "/dev/null"]
        subprocess.run(base + ["new-session", "-d", "-s", "t", f"cat > {out}"], check=True)
        try:
            with mock.patch.object(tb, "_base_argv", lambda: ["tmux", "-L", sock]), mock.patch.object(tb, "_exact", lambda n: "t"):
                for s in ("foo;", "bar\;", "x;y;"):
                    self.assertTrue(tb.tmux_send_raw("t", s))
            subprocess.run(base + ["send-keys", "-t", "t", "Enter", "C-d"])
            time.sleep(0.5)
            self.assertEqual(open(out).read().strip(), "foo;bar\;x;y;")
        finally:
            subprocess.run(base + ["kill-server"], capture_output=True)


if __name__ == "__main__":
    unittest.main()


class JobAttemptsResetOnStateChange(unittest.TestCase):
    """Onay bildirimi 5 kez düşse de iş bitince sonuç iletimi yeniden denenir (review cliops R-2)."""
    def test_state_change_resets_attempts(self):
        from claudeops import steward_jobs as sj
        rec = {"id": 1, "service": "varaka", "state": "awaiting_approval", "attempts": sj.DELIVER_MAX_ATTEMPTS, "notified": []}
        self.assertEqual(sj.pending_stage(rec), "")                       # onay aşamasında vazgeçildi
        upd = sj.apply_remote(rec, {"state": "done"}, 100.0)
        self.assertEqual(upd["attempts"], 0)
        rec.update(upd)
        self.assertEqual(sj.pending_stage(rec), "result")
        self.assertNotIn("attempts", sj.apply_remote(rec, {"state": "done"}, 101.0))   # aynı durum: sayaç korunur

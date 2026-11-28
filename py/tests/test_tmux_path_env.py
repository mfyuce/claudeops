"""P2-2 parça 2 (TBD#450): bağlı olmayan tmux istemcisinin açtığı oturumda pane PATH'i istemci sürecinin PATH'idir
(`new-session -e PATH=` bunu ezemez; tmux 3.2a'da ölçüldü). Oturumu açan istemciye süzülmüş PATH
(`paths.trusted_path_env`) verilir: doğrudan açmada alt sürecin `env`i, kabuk parçasında `PATH=... tmux` öneki.
Canlı servis YOK (argv/env; gerçek tmux denemesi `_tmux_iso` ile ayrı sınıfta)."""
import os
import shlex
import tempfile
import time
import unittest
from unittest import mock

from claudeops import tmux_backend as tb
from _tmux_iso import HAVE_TMUX, IsoTmux


class NewSessionPathEnv(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.missing = os.path.join(d.name, "tmp.yok")
        self.dirty = os.pathsep.join([self.missing, "/usr/bin", "/bin"])

    def test_spawn_direct_passes_trusted_path(self):
        calls = []

        def run(argv, **kw):
            calls.append(kw)
            return mock.Mock(returncode=0)
        with mock.patch.object(tb.subprocess, "run", run):
            self.assertTrue(tb.tmux_spawn_direct("a", "/", "x", {"PATH": self.dirty, "X": "1"}))
        self.assertEqual(calls[0]["env"], {"PATH": "/usr/bin:/bin", "X": "1"})

    def test_spawn_direct_without_path_in_env_uses_process_path(self):
        calls = []

        def run(argv, **kw):
            calls.append(kw)
            return mock.Mock(returncode=0)
        with mock.patch.object(tb.subprocess, "run", run), mock.patch.dict(os.environ, {"PATH": self.dirty}):
            tb.tmux_spawn_direct("a", "/", "x", {})
        self.assertEqual(calls[0]["env"], {"PATH": "/usr/bin:/bin"})

    def test_shell_fragment_passes_trusted_path(self):
        with mock.patch.dict(os.environ, {"PATH": self.dirty}):
            argv = shlex.split(tb.tmux_new_session_shell_fragment("a", "/", "x"))
        self.assertEqual(argv[:2], ["PATH=/usr/bin:/bin", "tmux"])
        self.assertEqual(argv[-1], "x")

    def test_no_trusted_entry_means_no_flag(self):
        with mock.patch.dict(os.environ, {"PATH": self.missing}):
            argv = shlex.split(tb.tmux_new_session_shell_fragment("a", "/", "x"))
        self.assertEqual(argv[0], "tmux")



@unittest.skipUnless(HAVE_TMUX, "tmux yok")
class RealTmuxPanePath(unittest.TestCase):
    """Gerçek tmux (yalıtılmış soket): sunucu genel ortamı kirli olsa da doğrudan açılan pane süzülmüş PATH'i görür."""
    def test_pane_sees_trusted_path(self):
        with IsoTmux() as iso, tempfile.TemporaryDirectory(dir="/tmp", prefix="cpe.") as d:
            out = os.path.join(d, "out")
            dirty = os.pathsep.join([os.path.join(d, "yok"), "/usr/bin", "/bin"])
            env = dict(iso.env, PATH=dirty)
            self.assertTrue(tb.tmux_spawn_direct("a", "/", f"echo $PATH > {out}; sleep 1", env))
            for _ in range(50):
                if os.path.exists(out) and os.path.getsize(out):
                    break
                time.sleep(0.1)
            with open(out) as f:
                self.assertEqual(f.read().strip(), "/usr/bin:/bin")


if __name__ == "__main__":
    unittest.main()

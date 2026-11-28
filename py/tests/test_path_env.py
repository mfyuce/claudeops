"""P2-2 (28 Kas): servis PATH'inde var olmayan `/tmp/tmp.*` dizini vardı; çok kullanıcılı makinede başkası o dizini kurup
`tmux` (ya da `claude`, `git`) koyarsa servis onu çalıştırırdı. `paths.trusted_path_env` güvenilmeyen girdileri atar:
göreli/boş, var olmayan, dizin olmayan, sahibi root ya da biz olmayan, başkalarınca (other) yazılabilir. Canlı servis YOK."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import paths  # noqa: E402


class TrustedPathEnv(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = d.name
        self.mine = os.path.join(self.root, "mine")
        os.mkdir(self.mine, 0o755)

    def test_keeps_trusted_and_order(self):
        val = os.pathsep.join([self.mine, "/usr/bin", "/bin"])
        self.assertEqual(paths.trusted_path_env(val), val)

    def test_drops_missing_relative_empty(self):
        missing = os.path.join(self.root, "tmp.aEx49Kzuf1")
        val = os.pathsep.join([missing, "", ".", "bin", self.mine, "/usr/bin"])
        self.assertEqual(paths.trusted_path_env(val), os.pathsep.join([self.mine, "/usr/bin"]))

    def test_drops_file_and_world_writable(self):
        f = os.path.join(self.root, "dosya")
        open(f, "w").close()
        ww = os.path.join(self.root, "ww")
        os.mkdir(ww)
        os.chmod(ww, 0o777)
        val = os.pathsep.join([f, ww, self.mine])
        self.assertEqual(paths.trusted_path_env(val), self.mine)

    def test_drops_foreign_owner(self):
        real = os.stat
        def fake(p, *a, **k):
            st = real(p, *a, **k)
            if os.path.realpath(p) == os.path.realpath(self.mine):
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, os.getuid() + 4242, st.st_gid,
                                       st.st_size, st.st_atime, st.st_mtime, st.st_ctime))
            return st
        with mock.patch.object(paths.os, "stat", fake):
            self.assertEqual(paths.trusted_path_env(os.pathsep.join([self.mine, "/usr/bin"])), "/usr/bin")

    def test_duplicates_kept_once(self):
        self.assertEqual(paths.trusted_path_env(os.pathsep.join(["/usr/bin", self.mine, "/usr/bin"])),
                         os.pathsep.join(["/usr/bin", self.mine]))

    def test_secure_environ_rewrites_and_reports(self):
        missing = os.path.join(self.root, "yok")
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([missing, self.mine])}):
            self.assertEqual(paths.secure_path_environ(), [missing])
            self.assertEqual(os.environ["PATH"], self.mine)
            self.assertEqual(paths.secure_path_environ(), [])
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(paths.secure_path_environ(), [])
            self.assertNotIn("PATH", os.environ)


if __name__ == "__main__":
    unittest.main()

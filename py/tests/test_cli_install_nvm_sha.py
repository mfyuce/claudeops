"""nvm kurulum betiği indirildikten sonra sabit sha256 ile doğrulanır; uyuşmazsa ÇALIŞTIRILMAZ (review cops R-5, curl | bash)."""
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from claudeops import cli_install as ci


class NvmShaGate(unittest.TestCase):
    def _run(self, content: bytes):
        d = tempfile.mkdtemp()
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)
            if argv[0] == "curl":
                open(argv[argv.index("-o") + 1], "wb").write(content)
            return subprocess.CompletedProcess(argv, 0, "", "")
        with mock.patch.object(ci, "INSTALL_DIR", d), mock.patch.object(ci, "NVM_SH", os.path.join(d, "nonexistent", "nvm.sh")), \
                mock.patch.object(ci.shutil, "which", lambda n: "/usr/bin/curl" if n == "curl" else None), \
                mock.patch.object(ci.subprocess, "run", fake_run):
            res = ci._ensure_node("tr")
        return res, calls

    def test_mismatch_not_executed(self):
        res, calls = self._run(b"echo evil\n")
        self.assertFalse(res["ok"])
        self.assertIn("sha256", res["error"])
        self.assertFalse([c for c in calls if c[0] == "bash"])                 # betik çalıştırılmadı

    def test_match_is_executed(self):
        import hashlib
        body = b"echo ok\n"
        with mock.patch.object(ci, "NVM_INSTALL_SCRIPT_SHA256", hashlib.sha256(body).hexdigest()):
            res, calls = self._run(body)
        self.assertTrue([c for c in calls if c[0] == "bash"])                  # özet tutunca çalıştırma yoluna girer

    def test_script_path_is_unique_and_removed(self):                         # review R-6: sabit `.install-nvm.sh` yarışı
        res, calls = self._run(b"echo evil\n")
        path = next(c for c in calls if c[0] == "curl")[-1]
        self.assertNotEqual(os.path.basename(path), ".install-nvm.sh")
        self.assertTrue(os.path.basename(path).startswith(".install-nvm-"))
        self.assertFalse(os.path.exists(path))
        res2, calls2 = self._run(b"echo evil\n")
        self.assertNotEqual(path, next(c for c in calls2 if c[0] == "curl")[-1])

    def test_install_via_script_uses_a_unique_path(self):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        seen = []

        def fake_run(argv, **kw):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        with mock.patch.object(ci, "INSTALL_DIR", d), mock.patch.object(ci.shutil, "which", lambda n: "/usr/bin/curl"), \
                mock.patch.object(ci.subprocess, "run", fake_run):
            self.assertTrue(ci._install_via_script("tool", "https://x.invalid/i.sh", "tr")["ok"])
        path = seen[0][seen[0].index("-o") + 1]
        self.assertTrue(os.path.basename(path).startswith(".install-tool-"))
        self.assertFalse(os.path.exists(path))

    def test_pin_is_hex64(self):
        self.assertRegex(ci.NVM_INSTALL_SCRIPT_SHA256, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()

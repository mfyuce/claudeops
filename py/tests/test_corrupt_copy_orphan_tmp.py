"""Öksüz `.corrupt-<sha8>.<pid>-*.tmp` temizliği (rs-state kapı notu).

`_write_corrupt_copy` geçici ad + `os.replace` ile yazar; süreç arada ölürse (SIGKILL, güç) geçici dosya kalır ve hiçbir
yol onu silmez. Bir sonraki yedek yazımı aynı belgenin ÖLÜ süreçten kalan geçici dosyalarını siler; canlı sürecinki
(yazım sürüyor olabilir), başka belgeninki ve normal dosya olmayanlar kalır.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops.atomic_json import _write_corrupt_copy  # noqa: E402


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class CorruptCopyOrphanTmpTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="corrupt-orphan-")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.doc = os.path.join(self.d, "instances.json")

    def _touch(self, name: str) -> str:
        p = os.path.join(self.d, name)
        with open(p, "wb") as f:
            f.write(b"half")
        return p

    def test_dead_pid_tmp_removed_live_and_foreign_kept(self):
        dead = _dead_pid()
        orphan_py = self._touch(f"instances.json.corrupt-aaaaaaaa.{dead}-140.tmp")
        orphan_rs = self._touch(f"instances.json.corrupt-bbbbbbbb.{dead}-rs3.tmp")
        live = self._touch(f"instances.json.corrupt-aaaaaaaa.{os.getppid()}-1.tmp")
        other_doc = self._touch(f"hosts.json.corrupt-aaaaaaaa.{dead}-1.tmp")
        odd = self._touch("instances.json.corrupt-aaaaaaaa.notapid-1.tmp")
        sup = self._touch("instances.json.corrupt-aaaaaaaa.\u00b2-1.tmp")     # isdigit() ama int() hatası
        os.symlink("/nonexistent", os.path.join(self.d, f"instances.json.corrupt-cccccccc.{dead}-2.tmp"))
        self.assertTrue(_write_corrupt_copy(self.doc + ".corrupt-12345678", b"raw"))
        self.assertFalse(os.path.exists(orphan_py))
        self.assertFalse(os.path.exists(orphan_rs))
        for keep in (live, other_doc, odd, sup):
            self.assertTrue(os.path.exists(keep), keep)
        self.assertTrue(os.path.islink(os.path.join(self.d, f"instances.json.corrupt-cccccccc.{dead}-2.tmp")))

    def test_unhashed_dest_sweeps_same_target_only(self):
        dead = _dead_pid()
        own = self._touch(f"orch.json.corrupt.{dead}-7.tmp")
        hashed = self._touch(f"orch.json.corrupt-aaaaaaaa.{dead}-7.tmp")
        _write_corrupt_copy(os.path.join(self.d, "orch.json.corrupt"), b"raw")
        self.assertFalse(os.path.exists(own))
        self.assertTrue(os.path.exists(hashed))

    def test_sweep_failure_does_not_block_backup(self):
        dead = _dead_pid()
        self._touch(f"instances.json.corrupt-aaaaaaaa.{dead}-1.tmp")
        os.chmod(self.d, 0o500)       # silinemez: yedek de yazılamaz, ama hata yalnız yedekten gelsin
        self.addCleanup(os.chmod, self.d, 0o700)
        if os.geteuid() == 0:
            self.skipTest("root izinleri yok saymaz")
        with self.assertRaises(PermissionError):
            _write_corrupt_copy(self.doc + ".corrupt-12345678", b"raw")


if __name__ == "__main__":
    unittest.main()

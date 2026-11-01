import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import logging, tempfile, unittest
from claudeops import atomic_json as aj


class TestFileLockFallback(unittest.TestCase):
    def test_symlink_lock_warns_once_and_still_runs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.json")
            os.symlink(os.path.join(d, "victim"), path + ".lock")      # O_NOFOLLOW reddeder -> kilitsiz devam
            aj._WARNED_LOCKS.discard(path)
            with self.assertLogs("claudeops.atomic_json", level="WARNING") as cm:
                with aj.file_lock(path):
                    ran = True
            self.assertTrue(ran)
            self.assertEqual(len(cm.output), 1)
            self.assertFalse(os.path.exists(os.path.join(d, "victim")))   # hedef yaratılmadı
            with self.assertNoLogs("claudeops.atomic_json", level="WARNING"):
                with aj.file_lock(path):
                    pass                                                  # ikinci kez uyarı yok

    def test_normal_lock_no_warning(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertNoLogs("claudeops.atomic_json", level="WARNING"):
                with aj.file_lock(os.path.join(d, "y.json")):
                    pass


if __name__ == "__main__":
    unittest.main()


class TestAtomicWriteTmp(unittest.TestCase):
    def test_utf8_with_mode_and_stale_symlink_tmp_not_followed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.json")
            victim = os.path.join(d, "victim")
            import threading
            tmp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
            os.symlink(victim, tmp)                                    # saldırgan/artık symlink: takip edilmemeli
            aj.atomic_write_json(path, {"ad": "şğüİ"}, mode=0o600)
            self.assertFalse(os.path.exists(victim))
            self.assertEqual(open(path, encoding="utf-8").read().count("şğüİ"), 1)   # ensure_ascii=False, utf-8
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_default_mode_respects_umask(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.umask(0o027)
            try:
                p = os.path.join(d, "b.json")
                aj.atomic_write_json(p, {"x": 1})
            finally:
                os.umask(old)
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o640)

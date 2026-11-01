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

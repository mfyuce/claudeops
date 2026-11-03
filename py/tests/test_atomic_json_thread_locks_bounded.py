"""atomic_json._THREAD_LOCKS path başına büyümez: kullanıcı kalmayınca girdi silinir; iç içe/eşanlı kullanım bozulmaz."""
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import atomic_json as aj  # noqa: E402


class ThreadLocksBoundedTest(unittest.TestCase):
    def test_entries_removed_after_use(self):
        before = len(aj._THREAD_LOCKS)
        with tempfile.TemporaryDirectory() as d:
            for i in range(50):
                with aj.file_lock(os.path.join(d, f"f{i}.json")):
                    pass
        self.assertEqual(len(aj._THREAD_LOCKS), before)

    def test_nested_same_path_ok_and_cleaned(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.json")
            with aj.file_lock(p):
                with aj.file_lock(p):
                    self.assertIn(p, aj._THREAD_LOCKS)
                self.assertIn(p, aj._THREAD_LOCKS)
            self.assertNotIn(p, aj._THREAD_LOCKS)

    def test_exception_still_cleans(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.json")
            with self.assertRaises(RuntimeError):
                with aj.file_lock(p):
                    raise RuntimeError("x")
            self.assertNotIn(p, aj._THREAD_LOCKS)

    def test_unusable_lock_file_warns_once_per_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "w.json")
            target = os.path.join(d, "elsewhere")
            with open(target, "w") as f:
                f.write("x")
            os.symlink(target, p + ".lock")     # O_NOFOLLOW -> OSError -> yalnız iş parçacığı kilidi
            self.addCleanup(aj._WARNED_LOCKS.discard, p)
            with self.assertLogs(aj.__name__, level="WARNING") as cm:
                for _ in range(3):
                    with aj.file_lock(p):
                        pass
            self.assertEqual(len(cm.records), 1)
            self.assertIn("alınamadı", cm.records[0].getMessage())
            self.assertNotIn(p, aj._THREAD_LOCKS)

    def test_concurrent_threads_stay_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            box = {"n": 0, "inside": 0, "bad": 0}

            def work():
                for _ in range(100):
                    with aj.file_lock(p):
                        box["inside"] += 1
                        if box["inside"] != 1:
                            box["bad"] += 1
                        box["n"] += 1
                        box["inside"] -= 1

            ts = [threading.Thread(target=work) for _ in range(6)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(30)
            self.assertEqual((box["n"], box["bad"]), (600, 0))
            self.assertNotIn(p, aj._THREAD_LOCKS)


if __name__ == "__main__":
    unittest.main()

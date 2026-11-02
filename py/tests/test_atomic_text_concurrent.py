"""atomic_write_text: eşzamanlı thread yazımları çakışmaz, mode=0o600 uygulanır, tmp artığı kalmaz."""
import os
import stat
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.atomic_json import atomic_write_text  # noqa: E402


class AtomicTextTest(unittest.TestCase):
    def test_concurrent_writers_leave_one_complete_file_and_no_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "r.md")
            errs = []

            def w(i):
                try:
                    atomic_write_text(path, (f"{i}-" * 2000) + "\n")
                except Exception as e:  # noqa: BLE001
                    errs.append(e)

            ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertEqual(errs, [])
            txt = open(path, encoding="utf-8").read()
            self.assertEqual(len(set(txt.strip().split("-")[:-1])), 1)   # tek yazarın tam içeriği
            self.assertEqual(os.listdir(os.path.dirname(path)), ["r.md"])

    def test_mode_600_and_unicode(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.md")
            atomic_write_text(path, "şğıİ", mode=0o600)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(open(path, encoding="utf-8").read(), "şğıİ")


if __name__ == "__main__":
    unittest.main()

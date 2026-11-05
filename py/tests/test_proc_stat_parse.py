"""/proc/<pid>/stat ayrıştırma TEK yardımcıda (paths.parse_proc_stat); comm'daki boşluk/parantez güvenli."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import paths  # noqa: E402
from claudeops import handover, discovery  # noqa: E402,F401


class ProcStatTest(unittest.TestCase):
    def test_plain(self):
        f = paths.parse_proc_stat("12 (bash) S 7 12 12 0 -1")
        self.assertEqual(f[0], "S")
        self.assertEqual(f[1], "7")

    def test_comm_with_space_and_paren(self):
        f = paths.parse_proc_stat("12 (we ird) (x) S 99 1 1")
        self.assertEqual((f[0], f[1]), ("S", "99"))

    def test_starttime_index(self):
        tail = " ".join(str(i) for i in range(30))
        self.assertEqual(paths.parse_proc_stat("5 (a) " + tail)[19], "19")

    def test_no_paren_raises(self):
        with self.assertRaises(ValueError):
            paths.parse_proc_stat("garbage")

    def test_own_ppid(self):
        self.assertEqual(paths.proc_ppid(os.getpid()), os.getppid())

    def test_no_inline_copies(self):
        base = os.path.join(os.path.dirname(paths.__file__))
        for rel in ("handover.py", "discovery.py", os.path.join("providers", "claude_provider.py"),
                    os.path.join("commands", "web_review.py")):
            src = open(os.path.join(base, rel), encoding="utf-8").read()
            self.assertNotIn('rsplit(")", 1)', src, rel)
            self.assertNotIn('rindex(")")', src, rel)


if __name__ == "__main__":
    unittest.main()

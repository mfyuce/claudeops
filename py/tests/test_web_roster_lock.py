"""WEB-08: _toggle_comment/_replace_tsv_line roster.lock flock'u altında çalışır (geçici dizin)."""
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


class RosterLockTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "roster.tsv")
        with open(self.p, "w", encoding="utf-8") as f:
            f.write("a\tx\nb\ty\n")

    def test_toggle_creates_lock_and_works(self):
        self.assertTrue(web._toggle_comment(self.p, "a", want_active=False))
        self.assertTrue(os.path.exists(os.path.join(self.d, "roster.lock")))
        with open(self.p, encoding="utf-8") as f:
            self.assertEqual(f.read(), "#a\tx\nb\ty\n")

    def test_replace_keeps_comment(self):
        web._toggle_comment(self.p, "b", want_active=False)
        self.assertTrue(web._replace_tsv_line(self.p, "b", ["b", "z"]))
        with open(self.p, encoding="utf-8") as f:
            self.assertEqual(f.read(), "a\tx\n#b\tz\n")

    def test_missing_file_false(self):
        self.assertFalse(web._toggle_comment(os.path.join(self.d, "nope.tsv"), "a", True))

    def test_concurrent_toggles_no_lost_update(self):
        with open(self.p, "w", encoding="utf-8") as f:
            f.write("".join("n%d\tv\n" % i for i in range(20)))
        ts = [threading.Thread(target=web._toggle_comment, args=(self.p, "n%d" % i, False))
              for i in range(20)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        with open(self.p, encoding="utf-8") as f:
            self.assertTrue(all(l.startswith("#") for l in f.read().splitlines()))


if __name__ == "__main__":
    unittest.main()

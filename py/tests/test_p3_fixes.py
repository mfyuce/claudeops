"""P3 review fixes: files root "/" prefix, steward_quota DST day boundary, atomic_json.file_lock reentrancy."""
import datetime
import os
import sys
import tempfile
import threading
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import atomic_json  # noqa: E402
from claudeops import files  # noqa: E402
from claudeops import steward_quota as q  # noqa: E402


class FilesRootTest(unittest.TestCase):
    def test_filesystem_root_allows_children(self):
        # cwd "/" -> real_root + os.sep == "//" used to match nothing
        got = files._resolve_within_roots("/usr", [("project", "/")])
        self.assertEqual(got, os.path.realpath("/usr"))
        self.assertEqual(files._resolve_within_roots("/", [("project", "/")]), os.path.realpath("/"))

    def test_sibling_prefix_still_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "a")
            sib = os.path.join(d, "ab")
            os.makedirs(root)
            os.makedirs(sib)
            self.assertIsNone(files._resolve_within_roots(sib, [("project", root)]))
            self.assertEqual(files._resolve_within_roots(root, [("project", root)]), os.path.realpath(root))


class QuotaDstTest(unittest.TestCase):
    def test_day_boundary_uses_wall_clock_across_dst_end(self):
        tz = ZoneInfo("America/New_York")      # DST ends Sun 2026-11-01 02:00
        reset = datetime.datetime(2026, 11, 2, 18, 0, tzinfo=tz).timestamp()
        u = q.Usage(week_pct=10.0, reset_ts=reset)
        # Sun 17:30 EST is still day 6 of the window (day 7 starts 18:00 wall clock); fixed 86400 s said day 7
        now = datetime.datetime(2026, 11, 1, 17, 30, tzinfo=tz).timestamp()
        self.assertEqual(q.day_label(u, now, tz), "sun")
        self.assertEqual(q.day_cap({"mode": "auto"}, u, now, tz), round(q.DEFAULT_FINAL * 6 / 7, 1))
        after = datetime.datetime(2026, 11, 1, 18, 30, tzinfo=tz).timestamp()
        self.assertEqual(q.day_cap({"mode": "auto"}, u, after, tz), round(q.DEFAULT_FINAL * 7 / 7, 1))


class FileLockReentrantTest(unittest.TestCase):
    def test_nested_same_thread_does_not_deadlock(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            done = []

            def run():
                with atomic_json.file_lock(p):
                    with atomic_json.file_lock(p):
                        done.append(1)

            t = threading.Thread(target=run, daemon=True)
            t.start()
            t.join(5)
            self.assertFalse(t.is_alive(), "nested file_lock deadlocked")
            self.assertEqual(done, [1])
            with atomic_json.file_lock(p):      # fully released afterwards
                pass


if __name__ == "__main__":
    unittest.main()

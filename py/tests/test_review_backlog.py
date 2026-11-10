"""L1 (10 Kas 2026): açık review satırı birikimi eşiği aşan projeye yeni otomatik review başlamaz (★ odak muaf)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402
from claudeops.commands import web_review  # noqa: E402

POOL = {"projects": {"a": {"enabled": True}, "b": {"enabled": True}, "c": {"enabled": True, "focus": True},
                     "d": {"enabled": False}}}


class BacklogTest(unittest.TestCase):
    def test_count_open_review_lines(self):
        text = ("- [ ] (review x:1) [P1] a.py:1: hata\n- [x] (review x:2) [P2] b.py:2: tamam\n"
                "  - [ ] (review x:3) [P3] girintili\n- [ ] başka iş (review değil)\nmetin - [ ] (review x:4) satır başı değil\n")
        self.assertEqual(rv.open_review_lines(text), 2)
        self.assertEqual(rv.open_review_lines(""), 0)

    def test_backlogged_projects(self):
        counts = {"a": 60, "b": 10, "c": 500, "d": 900}
        self.assertEqual(rv.backlogged_projects(POOL, counts.get, 50), ["a"])     # c odak (muaf), d kapalı
        self.assertEqual(rv.backlogged_projects(POOL, counts.get, 0), [])         # 0 = kapalı
        self.assertEqual(rv.backlogged_projects(POOL, lambda p: 1 / 0, 50), [])  # okunamayan sayaç engellemez

    def test_review_backlog_reads_todo_and_rtodo_with_cache(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "TODO.md"), "w") as f:
                f.write("- [ ] (review p:1) [P2] x\n" * 3)
            with open(os.path.join(d, "RTODO.md"), "w") as f:
                f.write("- [ ] (review p:2) [P3] y\n")
            web_review._BACKLOG_CACHE.clear()
            with mock.patch.object(web_review, "project_cwd", lambda n: d):
                self.assertEqual(web_review.review_backlog("p", now=1000.0), 4)
                with open(os.path.join(d, "TODO.md"), "w") as f:
                    f.write("")
                self.assertEqual(web_review.review_backlog("p", now=1100.0), 4)    # önbellek
                self.assertEqual(web_review.review_backlog("p", now=2000.0), 1)    # süre doldu
            with mock.patch.object(web_review, "project_cwd", lambda n: ""):
                self.assertEqual(web_review.review_backlog("yok", now=1.0), 0)
        web_review._BACKLOG_CACHE.clear()

    def test_next_review_skips_backlogged(self):
        targets = [rv.ReviewTarget("agy", "m", "m", "")]
        pool = {"projects": {"a": {"enabled": True}, "b": {"enabled": True}}}
        hist = {"pairs": {}, "runs": []}
        skip = rv.backlogged_projects(pool, {"a": 99, "b": 0}.get, 50)
        nxt = rv.next_review(pool, hist, targets, 1000.0, busy_projects=skip)
        self.assertEqual(nxt[0], "b")


if __name__ == "__main__":
    unittest.main()

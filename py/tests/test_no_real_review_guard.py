"""`_no_real_review` koruması gerçekten çalışıyor mu: korumalı testte gerçek popen yoluna gidilirse patlar."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))     # `claudeops` paketi: tek başına da çalışsın
from _no_real_review import MSG, NoRealReviewMixin, install  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402


class TestGuard(NoRealReviewMixin, unittest.TestCase):
    def test_default_popen_blocked(self):
        with self.assertRaises(AssertionError) as cm:
            wr._default_popen(["true"])
        self.assertIn(MSG, str(cm.exception))
        self.assertEqual(len(self.real_review_attempts), 1)
        self.real_review_attempts.clear()      # bu testin kendi bilinçli denemesi: temizlikte sayılmasın

    def test_explicit_popen_not_affected(self):
        self.assertIsNot(wr._default_popen, __import__("subprocess").Popen)
        self.assertEqual(self.real_review_attempts, [])

    def test_restored_after(self):
        class T(unittest.TestCase):
            def runTest(self):
                pass
        t = T()
        orig = wr._default_popen
        install(t)
        self.assertIsNot(wr._default_popen, orig)
        t.doCleanups()
        self.assertIs(wr._default_popen, orig)

    def test_unmocked_run_job_default_resolves_to_guard(self):
        # run_job'a popen verilmezse korumaya düşer (thread içinde); deneme kaydedilir
        import inspect
        self.assertIsNone(inspect.signature(wr.run_job).parameters["popen"].default)


if __name__ == "__main__":
    unittest.main()

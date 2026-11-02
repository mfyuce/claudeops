"""TBD#4: cleanup-backups — en yeni N kalır, eskiler tar.gz'ye taşınır, silinmez; dry-run varsayılan.

Çalıştırma:  python3 py/tests/test_cleanup_backups.py -v
"""
import argparse
import os
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import cleanup_backups as cb  # noqa: E402


class CleanupBackupsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = os.path.join(self.tmp.name, "backups")
        os.makedirs(self.d)
        for i in range(5):
            p = os.path.join(self.d, f"b{i}.json")
            with open(p, "w") as f:
                f.write(str(i))
            os.utime(p, (1000 + i, 1000 + i))

    def test_plan_keeps_newest(self):
        kept, old = cb.plan(self.d, 2)
        self.assertEqual(kept, ["b4.json", "b3.json"])
        self.assertEqual(sorted(old), ["b0.json", "b1.json", "b2.json"])

    def test_plan_ignores_existing_archives(self):
        open(os.path.join(self.d, "archive-x.tar.gz"), "w").close()
        kept, old = cb.plan(self.d, 10)
        self.assertNotIn("archive-x.tar.gz", kept + old)

    def test_plan_missing_dir(self):
        self.assertEqual(cb.plan(os.path.join(self.tmp.name, "yok"), 3), ([], []))

    def _args(self, **kw):
        return argparse.Namespace(**{"keep": 2, "apply": False, **kw})

    def test_dry_run_changes_nothing(self):
        with mock.patch.object(cb, "CLAUDEOPS_DIR", self.tmp.name):
            self.assertEqual(cb.run(self._args()), 0)
        self.assertEqual(len(os.listdir(self.d)), 5)

    def test_apply_archives_then_removes_originals(self):
        with mock.patch.object(cb, "CLAUDEOPS_DIR", self.tmp.name):
            self.assertEqual(cb.run(self._args(apply=True)), 0)
        names = sorted(os.listdir(self.d))
        arc = [n for n in names if n.endswith(".tar.gz")]
        self.assertEqual(len(arc), 1)
        self.assertEqual([n for n in names if not n.endswith(".tar.gz")], ["b3.json", "b4.json"])
        with tarfile.open(os.path.join(self.d, arc[0])) as tf:
            self.assertEqual(sorted(tf.getnames()), ["b0.json", "b1.json", "b2.json"])

    def test_nothing_to_archive(self):
        with mock.patch.object(cb, "CLAUDEOPS_DIR", self.tmp.name):
            self.assertEqual(cb.run(self._args(keep=10, apply=True)), 0)
        self.assertEqual(len(os.listdir(self.d)), 5)


if __name__ == "__main__":
    unittest.main()

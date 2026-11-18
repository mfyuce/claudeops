import unittest
from unittest import mock
from claudeops import discovery


class OrphanTests(unittest.TestCase):
    def test_fallback_name(self):
        self.assertEqual(discovery.fallback_name("ucli", "/a/b/revdev/", 7), "ucli@revdev#7")

    def test_terminal_lost(self):
        with mock.patch("os.readlink", return_value="/dev/pts/9 (deleted)"):
            self.assertTrue(discovery.terminal_lost(1))
        with mock.patch("os.readlink", return_value="/dev/pts/9"):
            self.assertFalse(discovery.terminal_lost(1))
        with mock.patch("os.readlink", side_effect=OSError):
            self.assertFalse(discovery.terminal_lost(1))

    def test_idle_spin(self):
        with mock.patch("os.readlink", return_value="/dev/null"):
            self.assertTrue(discovery.idle_spin(1, 88.0, False))
            self.assertFalse(discovery.idle_spin(1, 10.0, False))
            self.assertFalse(discovery.idle_spin(1, 88.0, True))


if __name__ == "__main__":
    unittest.main()


class OrphanReportTests(unittest.TestCase):
    def test_spin_after_ten_minutes(self):
        from claudeops.discovery import Session, orphan_report
        s = Session(name="u", pid=5, cwd="/x", cpu=90.0, cli="ucli")
        since = {}
        with mock.patch("os.readlink", return_value="/dev/pts/3 (deleted)"):
            r = orphan_report([s], lambda p: False, 1000.0, since)
            self.assertFalse(r[0]["spinning"])
            r = orphan_report([s], lambda p: False, 1601.0, since)
            self.assertTrue(r[0]["spinning"])
            s.cpu = 1.0
            r = orphan_report([s], lambda p: False, 1700.0, since)
            self.assertFalse(r[0]["spinning"])
            self.assertEqual(orphan_report([s], lambda p: True, 1700.0, since), [])

import unittest
from collections import namedtuple
from unittest import mock

from claudeops.commands import web_steward as ws

U = namedtuple("U", "total used free")


class DiskWatchTest(unittest.TestCase):
    def setUp(self):
        ws._DISK_WATCH.update(day="", notified=False)

    def run_w(self, used):
        with mock.patch("shutil.disk_usage", return_value=U(100 * 2**30, used * 2**30, (100 - used) * 2**30)), \
                mock.patch.object(ws, "notify_phone") as n, mock.patch.object(ws, "diag_log"):
            return ws.disk_watch(), n

    def test_warns_once_per_day(self):
        r, n = self.run_w(99)
        self.assertTrue(r["warned"]); n.assert_called_once()
        r, n = self.run_w(99)
        self.assertFalse(r["warned"]); n.assert_not_called()

    def test_below_threshold_silent_and_resets(self):
        r, n = self.run_w(50)
        self.assertFalse(r["warned"]); n.assert_not_called()
        self.run_w(99)
        self.run_w(50)
        r, n = self.run_w(99)
        self.assertTrue(r["warned"])


if __name__ == "__main__":
    unittest.main()

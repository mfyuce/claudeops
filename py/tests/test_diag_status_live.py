"""/api/status profili (TODO 972): `_diag_status(live)` verilen taramayı kullanır, ikinci find_sessions taraması YAPMAZ."""
import unittest
from unittest import mock

from claudeops.commands import web


class DiagStatusReusesLive(unittest.TestCase):
    def test_no_extra_scan_when_live_given(self):
        with mock.patch.object(web, "find_sessions", side_effect=AssertionError("ikinci tarama")) as fs:
            res = web._diag_status([])
        fs.assert_not_called()
        self.assertEqual(res["windowless"], [])

    def test_scans_when_live_missing(self):
        with mock.patch.object(web, "find_sessions", return_value=[]) as fs:
            web._diag_status()
        self.assertGreaterEqual(fs.call_count, 1)


if __name__ == "__main__":
    unittest.main()

"""689: `_live_mirror_entries` tarama patlarsa [] döner AMA diag.log'a iz bırakır (hepsi sahte; süreç/disk YOK)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


class MirrorEntriesDiagTest(unittest.TestCase):
    def test_failure_logged_and_empty(self):
        calls = []
        with mock.patch.object(web.mirrors, "running_mirrors", side_effect=RuntimeError("boom")), \
                mock.patch.object(web, "diag_log", lambda *a, **k: calls.append((a, k))):
            self.assertEqual(web._live_mirror_entries(), [])
        self.assertEqual(calls[0][0][0], "mirror_entries_failed")
        self.assertIn("boom", calls[0][1]["error"])

    def test_remote_only_sorted(self):
        specs = {"yuhem:b": 1, "local:x": 2, "yuhem:a": 3}
        with mock.patch.object(web.mirrors, "running_mirrors", return_value=specs):
            self.assertEqual(web._live_mirror_entries(),
                             [{"host": "yuhem", "name": "a"}, {"host": "yuhem", "name": "b"}])


if __name__ == "__main__":
    unittest.main()

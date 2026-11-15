"""review STILL düzeltmeleri (tur 4): bozuk draft JSON günlüğe düşer; kill sonrası wait."""
import json
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import orch_store  # noqa: E402


class StillsBatch1(unittest.TestCase):
    def test_corrupt_json_logged_and_default(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "draft.json")
        open(p, "w").write("{not json")
        with mock.patch.object(orch_store.statedocs if hasattr(orch_store, "statedocs") else __import__("claudeops.statedocs", fromlist=["x"]), "_db_ok", return_value=False):
            with self.assertLogs("claudeops.orch_store", level="WARNING") as cm:
                self.assertEqual(orch_store._load_json(p, {}), {})
        self.assertIn("bozuk JSON", cm.output[0])

    def test_missing_file_silent_default(self):
        from claudeops import statedocs
        with mock.patch.object(statedocs, "_db_ok", return_value=False):
            self.assertEqual(orch_store._load_json("/nonexistent/x.json", 7), 7)


if __name__ == "__main__":
    unittest.main()

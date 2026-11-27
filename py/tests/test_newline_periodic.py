"""Kullanıcı tanımlı periyodik iş kimliği sondaki satır sonunu kabul etmesin (yerleşik ad çakışması aşılıyordu)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import periodic as P  # noqa: E402


class TrailingNewlineJobIdTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        for p in (mock.patch.object(P, "CONFIG_JSON", os.path.join(self.d, "periodic.json")),
                  mock.patch.object(P, "STATE_JSON", os.path.join(self.d, "state.json"))):
            p.start()
            self.addCleanup(p.stop)

    def test_api_add_rejects_newline_id(self):
        builtin = sorted(P.JOBS)[0]
        for cid in ("myjob\n", builtin + "\n"):
            res = P.api_action({"action": "add", "id": cid, "fields": {"command": "true"}})
            self.assertFalse(res["ok"], repr(cid))
            self.assertNotIn(cid, P.load_config())

    def test_hand_edited_config_entry_is_ignored(self):
        with open(P.CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump({"custom": {"myjob\n": {"command": "true"}, "fine": {"command": "true"}}}, f)
        cfg = P.load_config()
        self.assertIn("fine", cfg)
        self.assertNotIn("myjob\n", cfg)


if __name__ == "__main__":
    unittest.main()

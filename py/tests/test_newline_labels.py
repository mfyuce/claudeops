"""Etiket adı/rengi doğrulaması sondaki satır sonunu kabul etmesin (`^...$` + `match`). Gerçek depoya dokunmaz."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import labels  # noqa: E402


class TrailingNewlineLabelTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.path = os.path.join(d.name, "labels.json")
        p = mock.patch.object(labels, "_path", lambda: self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_api_add_cannot_create_a_system_label_lookalike(self):
        res = labels.api_action({"name": "p", "add": ["stuck\n"]})
        self.assertFalse(res["ok"])
        self.assertEqual(labels.assignments(), {})
        self.assertNotIn("stuck\n", labels.definitions())

    def test_define_and_delete_reject_newline_name(self):
        self.assertFalse(labels.api_action({"define": {"name": "foo\n"}})["ok"])
        self.assertFalse(labels.api_action({"define": {"name": "stuck\n"}})["ok"])
        self.assertNotIn("foo\n", labels.definitions())
        self.assertIn("geçersiz", labels.api_action({"delete": "stuck\n"})["error"])

    def test_hand_edited_file_entries_are_dropped(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "defs": {"bad\n": {}, "ok": {"color": "#ffffff\n"}},
                       "assign": {"p": ["bad\n", "ok"]}}, f)
        defs = labels.definitions()
        self.assertNotIn("bad\n", defs)
        self.assertEqual(defs["ok"]["color"], labels.DEFAULT_COLOR)
        self.assertEqual(labels.assignments(), {"p": ["ok"]})


if __name__ == "__main__":
    unittest.main()

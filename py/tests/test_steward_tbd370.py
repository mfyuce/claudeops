"""TBD#370 (c): değnekçi saf çekirdeğindeki düzeltmeler (stdlib unittest; G/Ç yok)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings as settings_mod  # noqa: E402
from claudeops import steward as sw  # noqa: E402


class TrailingNewlineNameTest(unittest.TestCase):
    """`^...$` + `match` sondaki tek satır sonunu geçiriyordu; `"default\\n"` rezerve listesini aşıyordu."""

    def test_valid_name(self):
        for name in ("ab", "ancient-script-pipeline-fd", "a" * 47):
            self.assertTrue(sw.valid_name(name), repr(name))
            self.assertFalse(sw.valid_name(name + "\n"), repr(name))

    def test_valid_custom_id(self):
        self.assertTrue(sw.valid_custom_id("iso"))
        for sid in ("iso\n", "default\n", "all\n", "services\n", "degnekci\n", "ab\r\n"):
            self.assertFalse(sw.valid_custom_id(sid), repr(sid))

    def test_valid_steward_id(self):
        self.assertTrue(sw.valid_steward_id("default"))
        self.assertTrue(sw.valid_steward_id("iso"))
        for sid in ("default\n", "iso\n", "all\n"):
            self.assertFalse(sw.valid_steward_id(sid), repr(sid))

    def test_reviewer_ids(self):
        role = {"role": "reviewer"}
        st = {"stewards": {"reviewer": role, "iso\n": role, "default\n": role}}
        with mock.patch.object(settings_mod, "load_settings", return_value=st):
            self.assertEqual(sw.reviewer_ids(), frozenset({"reviewer"}))


if __name__ == "__main__":
    unittest.main()

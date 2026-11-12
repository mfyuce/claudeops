"""review R-3: sözlük alanlarında sayısal 0 silinmez ("boş" değil). review R-4: `cops test` alt sürece PYTHONPATH verir."""
import os
import sys
import unittest
from argparse import Namespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import settings  # noqa: E402
from claudeops.commands import test_cmd  # noqa: E402


class SettingsZeroTest(_Tmp):
    def test_numeric_zero_kept_empty_string_removes(self):
        settings.save_settings({"steward": {"max_active": 0, "mode": "act"}})
        cur = settings.load_settings()["steward"]
        self.assertEqual(cur.get("max_active"), "0")
        settings.save_settings({"steward": {"max_active": ""}})
        self.assertNotIn("max_active", settings.load_settings()["steward"])

    def test_false_still_off_and_bool_not_numeric(self):
        settings.save_settings({"steward": {"card_refresh": False}})
        self.assertEqual(settings.load_settings()["steward"].get("card_refresh"), "off")


class TestCmdEnvTest(unittest.TestCase):
    def test_pythonpath_has_py_root(self):
        calls = []
        with mock.patch.object(test_cmd.rt, "related_tests", lambda files, root, deep=False: {"test_x.py": ["x"]}), \
             mock.patch.object(test_cmd, "changed_files", lambda repo, base="": ["py/claudeops/x.py"]), \
             mock.patch.object(test_cmd.subprocess, "run", lambda *a, **k: calls.append(k) or mock.Mock(returncode=0)):
            rc = test_cmd.run(Namespace(files=[], base="", deep=False, list=False))
        self.assertEqual(rc, 0)
        py_root = os.path.abspath(os.path.join(os.path.dirname(test_cmd.__file__), "..", ".."))
        self.assertTrue(calls[0]["env"]["PYTHONPATH"].split(os.pathsep)[0] == py_root)


if __name__ == "__main__":
    unittest.main()

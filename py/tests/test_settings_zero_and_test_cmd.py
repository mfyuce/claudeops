"""review R-3: sözlük alanlarında sayısal 0 silinmez ("boş" değil). review R-4: `cops test` alt sürece PYTHONPATH verir."""
import contextlib
import io
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


class TestCmdBaseTest(unittest.TestCase):
    def test_unknown_base_fails_instead_of_selecting_nothing(self):
        out = io.StringIO()
        with mock.patch.object(test_cmd.subprocess, "run",
                               lambda cmd, **k: mock.Mock(returncode=128 if "yok...HEAD" in cmd else 0, stdout="")), \
             contextlib.redirect_stdout(out):
            rc = test_cmd.run(Namespace(files=[], base="yok", deep=False, list=True))
        self.assertEqual(rc, 2, out.getvalue())
        self.assertIn("taban okunamadı: yok", out.getvalue())


class TestCmdDistNoteTest(unittest.TestCase):
    def test_dist_files_not_counted_as_unselected(self):
        """`dist` dosyaları `test_webui_dist*` seçtirir; "python dışı, seçime girmedi" notunda sayılmaz."""
        py_root = os.path.abspath(os.path.join(os.path.dirname(test_cmd.__file__), "..", ".."))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = test_cmd.run(Namespace(files=[os.path.join(py_root, "webui", "dist", "index.html"),
                                               os.path.join(py_root, "..", "README.md")],
                                        base="", deep=False, list=True))
        self.assertEqual(rc, 0)
        self.assertIn("test_webui_dist_renders", out.getvalue())
        self.assertIn("python dışı 1 dosya", out.getvalue())


class TestCmdTmpNetTest(unittest.TestCase):
    def test_single_module_run_loads_tmp_net_first(self):
        """26 Kas edge: tek modül koşusunda mkdtemp ağı (`test_000_diag_env` -> `tmp_tracking`) kurulmuyordu."""
        calls = []
        with mock.patch.object(test_cmd.rt, "related_tests", lambda files, root, deep=False: {"test_x": ["x"]}), \
             mock.patch.object(test_cmd, "changed_files", lambda repo, base="": ["py/claudeops/x.py"]), \
             mock.patch.object(test_cmd.subprocess, "run", lambda cmd, **k: calls.append(cmd) or mock.Mock(returncode=0)), \
             contextlib.redirect_stdout(io.StringIO()):
            test_cmd.run(Namespace(files=[], base="", deep=False, list=False))
        self.assertEqual(calls[0][3:], ["test_000_diag_env", "test_x"])


if __name__ == "__main__":
    unittest.main()

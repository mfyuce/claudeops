"""L3 (10 Kas 2026): test koşucusu altında `CLAUDEOPS_DIR` hiçbir zaman canlı ~/.claude/claudeops olmaz (paths.py tek nokta)."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import paths  # noqa: E402
from claudeops import diaglog, settings  # noqa: E402

LIVE = os.path.realpath(os.path.join(os.path.expanduser("~"), ".claude", "claudeops"))
PY_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


class CustomRunnerTest(unittest.TestCase):
    """26 Kas 2026: argv'si ne `-m unittest` ne `test_*` olan özel koşucu betiği canlı dizine yazdırdı.
    Alt süreçte HOME geçici: kırmızı koşu bile canlıya değemez."""

    def _state_dir(self, prelude: str):
        with tempfile.TemporaryDirectory() as tmp:
            runner = os.path.join(tmp, "run.py")
            with open(runner, "w") as f:
                f.write(f"import sys\nsys.path.insert(0, {PY_DIR!r})\n{prelude}\n"
                        "from claudeops import paths\nprint(paths.CLAUDEOPS_DIR)\n")
            env = {k: v for k, v in os.environ.items() if k not in ("CLAUDEOPS_DIR", "CLAUDEOPS_TEST_REAL_DIR")}
            env["HOME"] = tmp
            out = subprocess.run([sys.executable, runner], env=env, capture_output=True, text=True, timeout=60, check=True)
            return out.stdout.strip(), os.path.join(tmp, ".claude", "claudeops")

    def test_script_that_loaded_unittest_is_isolated(self):
        got, live = self._state_dir("import unittest")
        self.assertNotEqual(got, live)

    def test_script_that_loaded_a_repo_test_module_is_isolated(self):
        fake = os.path.join(PY_DIR, "tests", "test_x.py")
        got, live = self._state_dir("import types\nm = types.ModuleType('test_x')\n"
                                    f"m.__file__ = {fake!r}\nsys.modules['test_x'] = m")
        self.assertNotEqual(got, live)

    def test_plain_script_uses_real_dir(self):
        got, live = self._state_dir("")
        self.assertEqual(got, live)


class IsolationTest(unittest.TestCase):
    def test_state_dir_is_not_live_under_runner(self):
        for p in (paths.CLAUDEOPS_DIR, os.path.dirname(settings.SETTINGS_JSON), os.path.dirname(diaglog.diag_log_path())):
            self.assertNotEqual(os.path.realpath(p), LIVE, p)
        self.assertEqual(os.environ.get("CLAUDEOPS_DIR"), paths.CLAUDEOPS_DIR)   # alt süreçler de devralır

    def test_runner_detection(self):
        with mock.patch.object(sys, "argv", ["python3 -m unittest"]), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDEOPS_TEST_REAL_DIR", None)
            self.assertTrue(paths._under_test_runner())
            os.environ["CLAUDEOPS_TEST_REAL_DIR"] = "1"
            self.assertFalse(paths._under_test_runner())
        with mock.patch.object(sys, "argv", ["/usr/bin/cops"]), mock.patch.dict(sys.modules, {"pytest": None, "_pytest": None}):
            sys.modules.pop("pytest", None)
            sys.modules.pop("_pytest", None)
            os.environ.pop("CLAUDEOPS_TEST_REAL_DIR", None)
            with mock.patch.object(paths, "_test_code_loaded", return_value=False):
                self.assertFalse(paths._under_test_runner())


if __name__ == "__main__":
    unittest.main()

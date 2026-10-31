"""web_orch düzeltmeleri: R-2 (çökmede sonuçlar korunur), R-4 (worker_timeout doğrulama),
R-5 (ek dosyalar 0600). Yalnız mock + tmp dizin; thread/ağ yok (stdlib unittest)."""
import math
import os
import stat
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_orch  # noqa: E402


class CrashKeepsResultsTest(unittest.TestCase):
    def test_unexpected_error_saves_accumulated_results(self):
        brief = mock.MagicMock(status="error", kind="brief", seq=1)
        ctrl = mock.MagicMock()
        with mock.patch.object(web_orch, "_eligible_index", return_value={}), \
                mock.patch.object(web_orch, "_build_brief_dispatch", return_value="p"), \
                mock.patch.object(web_orch, "_run_turn", return_value=brief), \
                mock.patch.object(web_orch, "_save_progress"), \
                mock.patch.object(web_orch, "_set_status"), \
                mock.patch.object(web_orch, "_build_dispatch_prompt", side_effect=RuntimeError("boom")), \
                mock.patch.object(web_orch, "_save_final") as sf, \
                mock.patch.object(web_orch, "diag_log"):
            web_orch._run_thread("r1", [], ctrl, None, "t", "", 5.0, threading.Event())
        sf.assert_called_once()
        saved = sf.call_args[0][1]
        self.assertEqual(saved, [brief])
        self.assertEqual(sf.call_args[0][3], "failed")


class WorkerTimeoutValidationTest(unittest.TestCase):
    def _timeout_for(self, raw):
        with mock.patch.object(web_orch, "start_run", return_value=("rid", None)) as sr:
            web_orch.http_start({"participants": [{"name": "a"}], "task": "x", "worker_timeout": raw})
        return sr.call_args[0][3]

    def test_bad_values_fall_back_to_default(self):
        for raw in (float("inf"), float("nan"), -5, 0, "0", "-1", "inf", "nan", "abc", float("-inf")):
            with self.subTest(raw=raw):
                self.assertEqual(self._timeout_for(raw), web_orch.DEFAULT_WORKER_TIMEOUT_SECONDS)

    def test_valid_value_is_kept(self):
        v = self._timeout_for(30)
        self.assertEqual(v, 30.0)
        self.assertTrue(math.isfinite(v))


class PrivateFilePermsTest(unittest.TestCase):
    def _mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_inline_or_file_writes_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.umask(0)
            try:
                with mock.patch.object(web_orch.orch_store, "run_dir", return_value=tmp), \
                        mock.patch.object(web_orch, "INLINE_LIMIT_CHARS", 5):
                    web_orch._inline_or_file("r", "x" * 50, "head", "tail", "task.md")
            finally:
                os.umask(old)
            self.assertEqual(self._mode(os.path.join(tmp, "task.md")), 0o600)

    def test_decider_bundle_writes_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.umask(0)
            try:
                with mock.patch.object(web_orch.orch_store, "run_dir", return_value=tmp), \
                        mock.patch.object(web_orch, "INLINE_LIMIT_CHARS", 5):
                    web_orch._build_decider_dispatch("r", "task", "", "b" * 50)
            finally:
                os.umask(old)
            self.assertEqual(self._mode(os.path.join(tmp, "decider_bundle.md")), 0o600)


if __name__ == "__main__":
    unittest.main()

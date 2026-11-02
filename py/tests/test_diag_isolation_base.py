"""DiagIsolatedTestCase taban sınıfı: yol geçici dizine döner, gerçek diag.log hash'i değişmez."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from diag_isolation import DiagIsolatedTestCase, REAL_DIAG_LOGS  # noqa: E402
from claudeops import diaglog  # noqa: E402


class BaseTest(DiagIsolatedTestCase):
    def test_path_is_temp_and_written(self):
        p = diaglog.diag_log_path()
        self.assertEqual(p, self.diag_log_file)
        self.assertNotIn(os.path.realpath(p), [os.path.realpath(r) for r in REAL_DIAG_LOGS])
        diaglog.diag_log("stop_end", name="cops", base_guard=True)
        self.assertTrue(os.path.exists(p))


if __name__ == "__main__":
    unittest.main()

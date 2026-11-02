"""Test taban sınıfı: diag.log yolu test başına geçici dizine alınır + gerçek diag.log hash guard'ı.

Kullanım:  from diag_isolation import DiagIsolatedTestCase  (py/tests dizini sys.path'te olmalı)
setUp: CLAUDEOPS_DIAG_LOG geçici dosyaya döner; tearDown: gerçek diag.log'un sha256'sı değiştiyse test BAŞARISIZ.
"""
import hashlib
import os
import tempfile
import unittest
from unittest import mock

REAL_DIAG_LOGS = (
    os.path.join(os.path.expanduser("~"), ".claude", "claudeops", "diag.log"),
)


def _digest(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


class DiagIsolatedTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._diag_dir = tempfile.TemporaryDirectory(prefix="cops-test-diag-")
        self.addCleanup(self._diag_dir.cleanup)
        self.diag_log_file = os.path.join(self._diag_dir.name, "diag.log")
        p = mock.patch.dict(os.environ, {"CLAUDEOPS_DIAG_LOG": self.diag_log_file})
        p.start()
        self.addCleanup(p.stop)
        self._real_before = {r: _digest(r) for r in REAL_DIAG_LOGS}
        self.addCleanup(self._check_real_untouched)

    def _check_real_untouched(self):
        after = {r: _digest(r) for r in REAL_DIAG_LOGS}
        self.assertEqual(self._real_before, after, "test gerçek diag.log'a yazdı")

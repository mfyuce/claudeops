"""tmp_tracking mkdtemp izleyicisi: oturum sonu temizliği için dizinler kayıtlı olmalı (21 Kas /tmp sızıntısı regresyonu)."""
import os
import tempfile
import unittest

import tmp_tracking


class TmpLeakGuardTest(unittest.TestCase):
    def test_mkdtemp_is_tracked(self):
        d = tempfile.mkdtemp()
        self.assertTrue(os.path.isdir(d))
        self.assertIn(d, tmp_tracking.CREATED)
        os.rmdir(d)

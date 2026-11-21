"""conftest.py mkdtemp izleyicisi: oturum sonu temizliği için dizinler kayıtlı olmalı (21 Kas /tmp sızıntısı regresyonu)."""
import os
import tempfile
import unittest

import conftest


class TmpLeakGuardTest(unittest.TestCase):
    def test_mkdtemp_is_tracked(self):
        d = tempfile.mkdtemp()
        self.assertTrue(os.path.isdir(d))
        self.assertIn(d, conftest._CREATED)
        os.rmdir(d)

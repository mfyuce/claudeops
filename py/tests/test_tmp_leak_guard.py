"""tmp_tracking mkdtemp izleyicisi: oturum sonu temizliği için dizinler kayıtlı olmalı (21 Kas /tmp sızıntısı regresyonu)."""
import os
import tempfile
import unittest
from unittest import mock

import tmp_tracking


class TmpLeakGuardTest(unittest.TestCase):
    def test_mkdtemp_is_tracked(self):
        d = tempfile.mkdtemp()
        self.assertTrue(os.path.isdir(d))
        self.assertIn(d, tmp_tracking.CREATED)
        os.rmdir(d)

    def test_mkstemp_and_named_delete_false_are_tracked_and_cleaned(self):
        """26 Kas edge: `mkstemp` ve `NamedTemporaryFile(delete=False)` ağda değildi."""
        fd, path = tempfile.mkstemp(prefix="cops-leak-")
        os.close(fd)
        with tempfile.NamedTemporaryFile(prefix="cops-leak-", delete=False) as f:
            named = f.name
        with tempfile.NamedTemporaryFile(prefix="cops-leak-") as f:
            auto = f.name
        self.assertIn(path, tmp_tracking.CREATED_FILES)
        self.assertIn(named, tmp_tracking.CREATED_FILES)
        self.assertNotIn(auto, tmp_tracking.CREATED_FILES)
        tmp_tracking.cleanup_files([path, named])
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(named))

    def test_file_cleanup_only_under_tempdir(self):
        """Ürün kodu `mkstemp(dir=hedef)` ile atomik yazıp yeniden adlandırır; geçici dizin dışı yol silinmez."""
        d = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, d)
        keep = os.path.join(d, "kalsin")
        open(keep, "w").close()
        self.addCleanup(os.unlink, keep)
        with mock.patch.object(tmp_tracking, "_TMP_ROOT", os.path.join(d, "baska") + os.sep):
            tmp_tracking.cleanup_files([keep])
        self.assertTrue(os.path.exists(keep))


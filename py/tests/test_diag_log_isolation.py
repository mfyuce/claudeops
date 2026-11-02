"""Guard: testler gerçek ~/.claude/claudeops/diag.log'a yazmaz (sahte stop_end name=cops olayları sızmasın)."""
import hashlib
import os
import sys
import tempfile
import unittest

# claudeops içe aktarılmadan ÖNCE yönlendir (tek başına unittest ile koşulsa da).
os.environ.setdefault("CLAUDEOPS_DIAG_LOG", os.path.join(tempfile.mkdtemp(prefix="cops-test-diag-"), "diag.log"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import diaglog  # noqa: E402
from claudeops.paths import CLAUDEOPS_DIR  # noqa: E402

REAL = os.path.join(os.path.expanduser("~"), ".claude", "claudeops", "diag.log")


def _digest(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


class DiagLogIsolation(unittest.TestCase):
    def test_diag_log_path_is_not_the_real_one(self):
        real = os.path.realpath(os.path.join(CLAUDEOPS_DIR, "diag.log"))
        self.assertNotEqual(os.path.realpath(diaglog.diag_log_path()), real)
        self.assertNotEqual(os.path.realpath(diaglog.diag_log_path()), os.path.realpath(REAL))

    def test_real_diag_log_hash_unchanged(self):
        before = (_digest(REAL), _digest(os.path.join(CLAUDEOPS_DIR, "diag.log")))
        diaglog.diag_log("stop_end", name="cops", guard=True)
        after = (_digest(REAL), _digest(os.path.join(CLAUDEOPS_DIR, "diag.log")))
        self.assertEqual(before, after)
        self.assertTrue(os.path.exists(diaglog.diag_log_path()))     # olay geçici dosyaya yazıldı


if __name__ == "__main__":
    unittest.main()

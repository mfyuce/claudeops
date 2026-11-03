"""GATE-TODO3 #1 (kok neden): `unittest discover` conftest.py'yi YUKLEMEZ (yalniz pytest), bu yuzden diag_log yolu
ayarlanmayan test modulleri gercek ~/.claude/claudeops/diag.log'a yaziyordu (`stop_end name=cops`, `token_file_is_symlink`).
Dosya adi `000`: discover tum modulleri testlerden ONCE alfabetik ice aktarir; yol diaglog'da CAGRI ZAMANINDA cozuldugu
icin bu modulun ice aktarimda kurdugu env tum suite icin gecerli olur. Tek dosya kosulurken diger taban siniflari
(steward_testlib, diag_isolation) kendi korumasini kurar.
Calistirma: python3 -m unittest discover -s py/tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REAL = os.path.join(os.path.expanduser("~"), ".claude", "claudeops", "diag.log")


def _needs_override():
    cur = os.environ.get("CLAUDEOPS_DIAG_LOG")
    return (not cur) or os.path.realpath(cur) == os.path.realpath(_REAL)


if _needs_override():
    os.environ["CLAUDEOPS_DIAG_LOG"] = os.path.join(tempfile.mkdtemp(prefix="cops-test-diag-"), "diag.log")


class DiagEnvTests(unittest.TestCase):
    def test_env_points_at_temp_not_real_log(self):
        cur = os.environ.get("CLAUDEOPS_DIAG_LOG")
        self.assertTrue(cur)
        self.assertNotEqual(os.path.realpath(cur), os.path.realpath(_REAL))

    def test_diag_log_path_follows_env(self):
        from claudeops import diaglog
        self.assertEqual(diaglog.diag_log_path(), os.environ["CLAUDEOPS_DIAG_LOG"])


if __name__ == "__main__":
    unittest.main()

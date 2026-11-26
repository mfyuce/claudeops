"""`unittest` koşusu (conftest.py'nin pytest kancası çalışmaz) arkasında geçici dizin bırakmaz (26 Kas: tam koşu 410 girdi bırakıyordu)."""
import os
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))


class UnittestRunLeavesNoTmpTest(unittest.TestCase):
    def _run(self, *args):
        return self._run_py("-m", "unittest", *args)

    def _run_py(self, *args):
        with tempfile.TemporaryDirectory(prefix="cops-leak-") as t:
            env = {k: v for k, v in os.environ.items() if k not in ("CLAUDEOPS_DIAG_LOG", "CLAUDEOPS_DIR")}
            env["TMPDIR"] = t
            r = subprocess.run([sys.executable, *args], cwd=TESTS, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            return sorted(os.listdir(t))

    def test_discover_style_run_cleans_up(self):
        """`test_000_diag_env` discover'da ilk içe aktarılır: sonrasında temizlenmeden bırakılan mkdtemp'ler de süreç sonunda silinir."""
        code = "import test_000_diag_env, tempfile, os; d = tempfile.mkdtemp(); open(os.path.join(d, 'f'), 'w').close(); tempfile.mkdtemp(prefix='x-')"
        self.assertEqual(self._run_py("-c", code), [])

    def test_single_module_run_cleans_up(self):
        """Ağ yüklenmeden tek modül koşusu (`cops test`): modül kendi dizinini kendisi siler."""
        self.assertEqual(self._run("test_store", "test_store_tsv", "test_statedocs", "test_statedocs_writers", "test_statedocs_hosts_diag",
                                   "test_agy_sids_store", "test_claude_models_store", "test_related_tests", "test_diag_log_isolation"), [])


if __name__ == "__main__":
    unittest.main()

import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import paths
from claudeops.commands import check


class CheckTest(unittest.TestCase):
    def test_compile_detects_syntax_error(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ok.py").write_text("x = 1\n")
            (Path(d) / "bad.py").write_text("def (:\n")
            errs = check.compile_all(Path(d))
        self.assertEqual(len(errs), 1)
        self.assertIn("bad.py", errs[0])

    def test_real_tree_compiles_and_imports(self):
        root = Path(check.__file__).resolve().parents[2]
        self.assertEqual(check.compile_all(root / "claudeops"), [])
        self.assertEqual(check.import_check(root), [])

    def _gate(self, script):
        """Geçici durum dizininde sahte commit-gate ikilisi (None = kurulu değil) ile uyarıları döndür."""
        with tempfile.TemporaryDirectory() as d:
            if script is not None:
                exe = Path(d) / "bin" / "commit-gate"
                exe.parent.mkdir()
                exe.write_text("#!/bin/sh\n" + script + "\n")
                exe.chmod(0o755)
            with mock.patch.object(paths, "CLAUDEOPS_DIR", d):
                return check._gate_warnings(Path(d))

    def test_gate_missing_binary_warns(self):
        self.assertIn("kurulu değil", self._gate(None)[0])

    def test_gate_clean_is_silent_and_gets_core_arg(self):
        self.assertEqual(self._gate('[ "$1" = check ] && [ "$2" = --core ] || echo "yanlis arguman" >&2'), [])

    def test_gate_failure_lines_become_warnings(self):
        self.assertEqual(self._gate("echo kural-ihlali >&2; exit 1"), ["kural-ihlali"])
        self.assertIn("çıkış kodu 2", self._gate("exit 2")[0])


if __name__ == "__main__":
    unittest.main()

import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
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


if __name__ == "__main__":
    unittest.main()

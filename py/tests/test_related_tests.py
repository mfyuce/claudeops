import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import related_tests as rt


def _w(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class RelatedTestsTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cops-rt-")
        r = self.root
        _w(f"{r}/claudeops/__init__.py")
        _w(f"{r}/claudeops/a.py", "X = 1\n")
        _w(f"{r}/claudeops/b.py", "from . import a\n")
        _w(f"{r}/claudeops/commands/__init__.py")
        _w(f"{r}/claudeops/commands/c.py", "from ..b import thing\n")
        _w(f"{r}/tests/test_a.py", "from claudeops import a as aa\n")
        _w(f"{r}/tests/test_b.py", "from claudeops.b import y\n")
        _w(f"{r}/tests/test_c.py", "from unittest import mock\nmock.patch('claudeops.commands.c.something')\n")
        _w(f"{r}/tests/test_none.py", "import os\n")

    def sel(self, *files, deep=False):
        return rt.related_tests([os.path.join(self.root, f) for f in files], self.root, deep=deep)

    def test_module_of(self):
        self.assertEqual(rt.module_of(f"{self.root}/claudeops/commands/c.py", self.root), "claudeops.commands.c")
        self.assertEqual(rt.module_of(f"{self.root}/claudeops/commands/__init__.py", self.root), "claudeops.commands")
        self.assertIsNone(rt.module_of(f"{self.root}/README.md", self.root))

    def test_direct_import_and_patch_string(self):
        self.assertEqual(list(self.sel("claudeops/a.py")), ["test_a"])
        self.assertEqual(list(self.sel("claudeops/commands/c.py")), ["test_c"])

    def test_deep_follows_relative_reverse_imports(self):
        self.assertEqual(list(self.sel("claudeops/a.py", deep=True)), ["test_a", "test_b", "test_c"])

    def test_changed_test_file_selected_itself(self):
        self.assertEqual(self.sel("tests/test_none.py"), {"test_none": ["(test)"]})

    def test_non_python_selects_nothing(self):
        self.assertEqual(self.sel("README.md"), {})


if __name__ == "__main__":
    unittest.main()

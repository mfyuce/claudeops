"""rs/prov G8: `run_checks` kayıt okuyucusu (`ucli_checks`). Yalnız geçici dizin."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_checks as ck  # noqa: E402


class Registry(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        p = mock.patch.object(ck, "ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)
        self.path = os.path.join(self.root, "owner.json")

    def put(self, body, path=None):
        path = path or self.path
        with open(path, "w") as f:
            f.write(body)
        os.chmod(path, 0o600)

    def test_names_and_owner_must_be_exact_strings(self):
        for name in ("a\n", float("inf"), float("nan"), 5, True):
            self.assertFalse(ck.check_shape({"check": [{"name": name, "argv": ["x"]}]})[0], repr(name))
        self.assertTrue(ck.check_shape({"check": [{"name": "inf", "argv": ["x"]}]})[0])
        with self.assertRaises(ValueError):
            ck.registry_path("owner\n")

    def test_deeply_nested_registry_is_an_error_not_an_exception(self):
        self.put("[" * 100000)
        self.assertEqual(ck.load_registry(), ({}, "kayıt geçerli JSON değil"))

    def test_swapped_for_a_link_after_the_check_is_not_followed(self):
        target = os.path.join(self.root, "other")
        self.put(json.dumps({"check": []}), target)
        self.put(json.dumps({"check": []}))
        real = os.lstat

        swapped = []

        def lstat_then_swap(path, *a, **kw):
            st = real(path, *a, **kw)
            if path == self.path and not swapped:
                swapped.append(1)
                os.remove(path)
                os.symlink(target, path)
            return st
        with mock.patch.object(ck.os, "lstat", lstat_then_swap):
            data, err = ck.load_registry()
        self.assertEqual((data, err), ({}, "kayıt geçerli JSON değil"))

    def test_swapped_for_a_loose_file_after_the_check_is_refused(self):
        self.put(json.dumps({"check": []}))
        real = os.lstat

        def lstat_then_loosen(path, *a, **kw):
            st = real(path, *a, **kw)
            if path == self.path:
                os.chmod(path, 0o666)
            return st
        with mock.patch.object(ck.os, "lstat", lstat_then_loosen):
            self.assertEqual(ck.load_registry(), ({}, "kayıt dosyası 0600 olmalı"))


if __name__ == "__main__":
    unittest.main()

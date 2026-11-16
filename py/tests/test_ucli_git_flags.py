"""ucli `--allow-git-commit` / `--allow-git-push` (cli_opts `git_commit` / `git_push`): doğrulama + argv + bayrak kapısı.
Gerçek Popen/ağ yok. Çalıştırılmadı (yazıldığı oturumda test koşturulamadı)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.ucli_session_opts import validate_opts  # noqa: E402


def apply(opts, supports=lambda b, f: True):
    with mock.patch.object(up, "binary_supports_flag", supports), \
            mock.patch.object(up, "_default_session_cap", return_value=0):
        return up._apply_cli_opts(["ucli"], opts, "sess1", "/tmp", "")


class ValidateTests(unittest.TestCase):
    def test_default_off(self):
        self.assertEqual(validate_opts({"service": "evren"}), ({"service": "evren"}, ""))
        out, err = validate_opts({"git_commit": False, "git_push": "false"})
        self.assertEqual((out, err), ({}, ""))

    def test_on_independent_of_each_other_and_exec(self):
        self.assertEqual(validate_opts({"git_push": True}), ({"git_push": True}, ""))
        self.assertEqual(validate_opts({"git_commit": "true"}), ({"git_commit": True}, ""))
        out, err = validate_opts({"git_commit": True, "git_push": True})
        self.assertEqual((out, err), ({"git_commit": True, "git_push": True}, ""))

    def test_garbage_is_error(self):
        out, err = validate_opts({"git_push": "maybe"})
        self.assertEqual(out, {})
        self.assertIn("git_push", err)


class ArgvTests(unittest.TestCase):
    def test_no_flags_by_default(self):
        argv, _ = apply({})
        self.assertNotIn("--allow-git-commit", argv)
        self.assertNotIn("--allow-git-push", argv)

    def test_only_requested_flag(self):
        argv, _ = apply({"git_commit": True})
        self.assertIn("--allow-git-commit", argv)
        self.assertNotIn("--allow-git-push", argv)
        argv, _ = apply({"git_push": True})
        self.assertIn("--allow-git-push", argv)
        self.assertNotIn("--allow-git-commit", argv)

    def test_both_no_duplicates(self):
        argv, _ = apply({"git_commit": True, "git_push": True})
        self.assertEqual(argv.count("--allow-git-commit"), 1)
        self.assertEqual(argv.count("--allow-git-push"), 1)

    def test_unsupported_binary_refuses(self):
        with self.assertRaises(ValueError):
            apply({"git_push": True}, supports=lambda b, f: False)

    def test_unsupported_irrelevant_when_off(self):
        argv, _ = apply({}, supports=lambda b, f: False)
        self.assertEqual(argv, ["ucli"])


if __name__ == "__main__":
    unittest.main()

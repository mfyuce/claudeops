"""ucli grup D bayrakları: --allow-image, --allow-scholar, --ask-edit.
`--exec-net` ve sınırsız `--allow-exec-own` BİLEREK sunulmaz (sahip kararı bekliyor); `exec_own_glob` zaten vardı.
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
            mock.patch.object(up, "_default_session_cap", return_value=0), \
            mock.patch.object(up, "path_executables", return_value={}), \
            mock.patch.object(up, "expand_exec_cmds", lambda cmds, _p: (list(cmds), "")):
        return up._apply_cli_opts(["ucli", "chat"], opts)[0]


EXEC = {"exec_cmds": "git", "exec_write": True}


class CapabilityFlagsTest(unittest.TestCase):
    def test_default_off(self):
        out, err = validate_opts({})
        self.assertEqual(err, "")
        for k in ("allow_image", "allow_scholar", "ask_edit"):
            self.assertNotIn(k, out)
        argv = apply(out)
        for f in ("--allow-image", "--allow-scholar", "--ask-edit"):
            self.assertNotIn(f, argv)

    def test_image_scholar_independent_of_exec(self):
        out, err = validate_opts({"allow_image": True, "allow_scholar": "true"})
        self.assertEqual(err, "")
        argv = apply(out)
        self.assertEqual(argv.count("--allow-image"), 1)
        self.assertEqual(argv.count("--allow-scholar"), 1)

    def test_false_values_dropped(self):
        out, err = validate_opts({"allow_image": "false", "ask_edit": 0})
        self.assertEqual(err, "")
        self.assertEqual(out, {})

    def test_invalid_value_is_error(self):
        for k in ("allow_image", "allow_scholar", "ask_edit"):
            out, err = validate_opts({**EXEC, k: "maybe"})
            self.assertTrue(err, k)
            self.assertEqual(out, {})

    def test_net_and_unbounded_exec_own_not_offered(self):
        out, _ = validate_opts({**EXEC, "exec_net": True, "exec_own": True})
        self.assertNotIn("exec_net", out)
        self.assertNotIn("exec_own", out)
        argv = apply({**EXEC, "exec_net": True, "exec_own": True})
        self.assertNotIn("--exec-net", argv)
        self.assertNotIn("--allow-exec-own", argv)

    def test_ask_edit_needs_write(self):
        out, err = validate_opts({"exec_cmds": "git", "ask_edit": True})
        self.assertTrue(err)
        out, err = validate_opts({**EXEC, "ask_edit": True})
        self.assertEqual(err, "")
        self.assertIs(out["ask_edit"], True)

    def test_exec_argv(self):
        out, err = validate_opts({**EXEC, "ask_edit": True})
        self.assertEqual(err, "")
        argv = apply(out)
        for f in ("--ask-edit", "--allow-edit"):
            self.assertEqual(argv.count(f), 1, f)

    def test_unsupported_binary_refuses(self):
        out, _ = validate_opts({"allow_image": True})
        with self.assertRaises(ValueError):
            apply(out, supports=lambda b, f: False)
        out, _ = validate_opts({**EXEC, "ask_edit": True})
        with self.assertRaises(ValueError):
            apply(out, supports=lambda b, f: f != "--ask-edit")

    def test_unsupported_but_off_no_error(self):
        argv = apply({}, supports=lambda b, f: False)
        self.assertNotIn("--ask-edit", argv)


if __name__ == "__main__":
    unittest.main()

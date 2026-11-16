"""ucli `--instructions-user` / `--instructions-max-kib` (cli_opts `instructions_user` / `instructions_max_kib`).
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
        return up._apply_cli_opts(["ucli", "chat"], opts)[0]


class InstructionsFlagsTest(unittest.TestCase):
    def test_default_off(self):
        out, err = validate_opts({})
        self.assertEqual(err, "")
        self.assertNotIn("instructions_user", out)
        self.assertNotIn("instructions_max_kib", out)
        argv = apply(out)
        self.assertNotIn("--instructions-user", argv)
        self.assertNotIn("--instructions-max-kib", argv)

    def test_valid(self):
        out, err = validate_opts({"instructions_user": True, "instructions_max_kib": "128"})
        self.assertEqual(err, "")
        self.assertIs(out["instructions_user"], True)
        self.assertEqual(out["instructions_max_kib"], 128)

    def test_zero_and_empty_dropped(self):
        out, err = validate_opts({"instructions_user": "false", "instructions_max_kib": "0"})
        self.assertEqual(err, "")
        self.assertNotIn("instructions_user", out)
        self.assertNotIn("instructions_max_kib", out)

    def test_invalid(self):
        for raw in ({"instructions_max_kib": "257"}, {"instructions_max_kib": "-1"},
                    {"instructions_max_kib": "abc"}, {"instructions_user": "maybe"}):
            out, err = validate_opts(raw)
            self.assertTrue(err, raw)
            self.assertEqual(out, {})

    def test_argv(self):
        argv = apply({"instructions_user": True, "instructions_max_kib": 64})
        self.assertEqual(argv.count("--instructions-user"), 1)
        self.assertEqual(argv[argv.index("--instructions-max-kib") + 1], "64")

    def test_unsupported_binary_skips(self):
        argv = apply({"instructions_user": True, "instructions_max_kib": 64}, supports=lambda b, f: False)
        self.assertNotIn("--instructions-user", argv)
        self.assertNotIn("--instructions-max-kib", argv)


if __name__ == "__main__":
    unittest.main()

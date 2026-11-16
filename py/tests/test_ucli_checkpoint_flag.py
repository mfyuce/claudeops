"""ucli `--checkpoint` (cli_opts `checkpoint`): varsayılan kapalı, belirsiz değer hata, desteklenmiyorsa atla.
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


class CheckpointFlagTest(unittest.TestCase):
    def test_default_off(self):
        out, err = validate_opts({})
        self.assertEqual(err, "")
        self.assertNotIn("checkpoint", out)
        self.assertNotIn("--checkpoint", apply({}))

    def test_false_values_dropped(self):
        for v in (False, "false", "0", "", None):
            out, err = validate_opts({"checkpoint": v})
            self.assertEqual(err, "")
            self.assertNotIn("checkpoint", out)

    def test_true_accepted(self):
        out, err = validate_opts({"checkpoint": True})
        self.assertEqual(err, "")
        self.assertIs(out["checkpoint"], True)

    def test_ambiguous_is_error(self):
        _, err = validate_opts({"checkpoint": "maybe"})
        self.assertTrue(err)

    def test_argv_added_once(self):
        argv = apply({"checkpoint": True})
        self.assertEqual(argv.count("--checkpoint"), 1)

    def test_unsupported_binary_skipped_not_rejected(self):
        argv = apply({"checkpoint": True}, supports=lambda b, f: False)
        self.assertNotIn("--checkpoint", argv)


if __name__ == "__main__":
    unittest.main()

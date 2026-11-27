"""Yoklanamayan ucli (zaman aşımı, çalıştırılamayan ikili) kaydı doğrulamasız yazdırmaz; yalnız "alt komut yok"
(eski ikili, sıfır olmayan çıkış) biçim denetimiyle yazılır. Nesne olmayan doğrulama çıktısı istisna atmaz, reddeder."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_checks as uck  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        p = mock.patch.object(uck, "ROOT", os.path.join(d.name, "ucli_checks"))
        p.start()
        self.addCleanup(p.stop)
        self.data = {"check": [uck.TEMPLATES["git log"]]}

    def binary(self, body, mode=0o755):
        path = os.path.join(self.dir, "ucli")
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, mode)
        return path

    def assertRejected(self, binary, needle):
        ok, why = uck.save_registry(self.data, binary=binary)
        self.assertFalse(ok, why)
        self.assertIn(needle, why)
        self.assertFalse(os.path.exists(uck.registry_path()))


class ProbeFailure(Base):
    def test_missing_binary_rejects_and_writes_nothing(self):
        self.assertRejected(os.path.join(self.dir, "yok"), "FileNotFoundError")

    def test_non_executable_binary_rejects(self):
        self.assertRejected(self.binary("exit 0", mode=0o644), "PermissionError")

    def test_probe_timeout_rejects(self):
        with mock.patch.object(uck.subprocess, "run", side_effect=subprocess.TimeoutExpired("ucli", 10)):
            self.assertRejected("/x/ucli", "TimeoutExpired")

    def test_probe_killed_by_signal_rejects(self):
        self.assertRejected(self.binary("kill -KILL $$"), "sinyal")

    def test_probe_unexpected_exit_code_rejects(self):
        self.assertRejected(self.binary("exit 127"), "127")

    def test_delete_still_works_when_binary_cannot_be_probed(self):
        two = [uck.TEMPLATES["git log"], uck.TEMPLATES["git diff"]]
        self.assertEqual(uck.save_registry({"check": two}), (True, ""))
        self.assertEqual(uck.delete_check("git-diff", binary=os.path.join(self.dir, "yok")), (True, ""))
        self.assertEqual([c["name"] for c in uck.load_registry()[0]["check"]], ["git-log"])

    def test_old_binary_without_subcommand_still_saves(self):
        self.assertEqual(uck.save_registry(self.data, binary=self.binary("exit 2")), (True, ""))


class ValidateOutputShape(Base):
    def test_non_object_output_rejects(self):
        for out in ("[]", "1", '"x"', "null", '{"ok": false, "errors": ["bozuk"]}', '{"ok": false, "errors": 5}'):
            with self.subTest(out=out):
                self.assertRejected(self.binary("echo '" + out + "'"), "")

    def test_ok_true_with_failing_exit_rejects(self):
        self.assertRejected(self.binary("[ \"$3\" = --help ] && exit 0; echo '{\"ok\": true}'; exit 1"), "geçersiz")


if __name__ == "__main__":
    unittest.main()

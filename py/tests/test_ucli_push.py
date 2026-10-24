"""`ucli-push`: sahneleme + sha256 doğrulama. Panel/ağ YOK: upload ve indirme taklit edilir."""
import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import ucli_push as up  # noqa: E402


class PushTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.bin = os.path.join(d.name, "ucli")
        with open(self.bin, "wb") as f:
            f.write(b"\x7fELF-fake" * 100)
        self.sha = hashlib.sha256(open(self.bin, "rb").read()).hexdigest()

    def test_dry_run_touches_nothing(self):
        with mock.patch.object(up, "upload") as u:
            r = up.push(1, "ulak_31", "s", binary=self.bin, dry=True)
        self.assertEqual((r["ok"], r["sha256"], r["size"]), (True, self.sha[:12], 900))
        u.assert_not_called()

    def test_live_name_and_path_in_filename_refused(self):
        for bad in ("ucli", "../x", "a/b", ""):
            self.assertFalse(up.push(1, "h", "s", filename=bad, binary=self.bin)["ok"])

    def test_verified_and_mismatch(self):
        with mock.patch.object(up, "upload", return_value={"ok": True, "path": "/w/ucli.new"}), \
                mock.patch.object(up, "remote_sha256", return_value=(self.sha, 900, "")):
            r = up.push(1, "h", "s", binary=self.bin)
        self.assertTrue(r["verified"])
        self.assertTrue(all("ucli.new" in x or "ucli" in x for x in r["next_steps"]))
        with mock.patch.object(up, "upload", return_value={"ok": True, "path": "/w/ucli.new"}), \
                mock.patch.object(up, "remote_sha256", return_value=("0" * 64, 5, "")):
            r = up.push(1, "h", "s", binary=self.bin)
        self.assertFalse(r["ok"])
        self.assertIn("uyuşmadı", r["error"])

    def test_upload_failure_reported(self):
        with mock.patch.object(up, "upload", return_value={"ok": False, "error": "exists"}):
            self.assertFalse(up.push(1, "h", "s", binary=self.bin)["ok"])


if __name__ == "__main__":
    unittest.main()

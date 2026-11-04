"""GATE-REVIEW-P5: files.write_text fsync-sonra-replace sirasi; _resolve_within_roots kok "/" ve on-ek sinirlari.
Gecici dizin; Session yerine _writable_roots sahtelenir."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import files  # noqa: E402


class WriteTextFsyncTest(unittest.TestCase):
    def test_fsync_before_replace_and_content_written(self):
        with tempfile.TemporaryDirectory() as d:
            real_d = os.path.realpath(d)
            target = os.path.join(real_d, "a.txt")
            with open(target, "w", encoding="utf-8") as f:
                f.write("eski")
            order = []
            real_fsync, real_replace = os.fsync, os.replace
            with mock.patch.object(files, "_writable_roots", lambda s: [("project", real_d)]), \
                    mock.patch("os.fsync", side_effect=lambda fd: (order.append("fsync"), real_fsync(fd))[1]), \
                    mock.patch("os.replace", side_effect=lambda a, b: (order.append("replace"), real_replace(a, b))[1]):
                res = files.write_text(object(), target, "yeni")
            self.assertEqual(res, {"ok": True})
            self.assertEqual(order, ["fsync", "replace", "fsync"])   # son fsync = dizin (rename kalıcı)
            with open(target, encoding="utf-8") as f:
                self.assertEqual(f.read(), "yeni")
            self.assertEqual([n for n in os.listdir(real_d) if n != "a.txt"], [])

    def test_outside_root_is_forbidden_and_missing_file_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            real_d = os.path.realpath(d)
            with mock.patch.object(files, "_writable_roots", lambda s: [("project", real_d)]):
                self.assertEqual(files.write_text(object(), os.path.join(real_d, "yok.txt"), "x")["error"], "not_found")
                self.assertEqual(files.write_text(object(), "/etc/hostname", "x")["error"], "forbidden")


class ResolveWithinRootsTest(unittest.TestCase):
    def test_slash_root_accepts_any_absolute_path(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.realpath(d)
            self.assertEqual(files._resolve_within_roots(d, [("project", "/")]), real)

    def test_sibling_with_same_prefix_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(os.path.realpath(d), "proj")
            sibling = root + "x"
            os.makedirs(root)
            os.makedirs(sibling)
            self.assertIsNone(files._resolve_within_roots(sibling, [("project", root)]))
            self.assertEqual(files._resolve_within_roots(root, [("project", root)]), root)


if __name__ == "__main__":
    unittest.main()

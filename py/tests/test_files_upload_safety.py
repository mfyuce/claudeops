"""Upload güvenliği: son bileşen symlink ile kök dışına yazılmaz; eksik gövde kaydedilmez (mevcut dosya bozulmaz)."""
import io
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import files  # noqa: E402


class UploadSafetyTest(unittest.TestCase):
    def setUp(self):
        base = os.path.realpath(tempfile.mkdtemp())
        self.root = os.path.join(base, "proj")
        self.out = os.path.join(base, "outside")
        os.makedirs(self.root)
        os.makedirs(self.out)
        self.s = NS(cwd=self.root, cli="shell")

    def test_symlink_to_outside_refused(self):
        victim = os.path.join(self.out, "victim.txt")
        open(victim, "w").write("ESKI")
        os.symlink(victim, os.path.join(self.root, "link.txt"))
        for ow in (False, True):
            dest, code = files.resolve_upload_target(self.s, None, "link.txt", overwrite=ow)
            self.assertIsNone(dest)
            self.assertEqual(code, "forbidden")
        self.assertEqual(open(victim).read(), "ESKI")

    def test_dangling_symlink_to_outside_refused(self):
        os.symlink(os.path.join(self.out, "yeni.txt"), os.path.join(self.root, "dangle.txt"))
        dest, code = files.resolve_upload_target(self.s, None, "dangle.txt", overwrite=True)
        self.assertEqual((dest, code), (None, "forbidden"))

    def test_symlink_inside_root_resolves_to_real_file(self):
        real = os.path.join(self.root, "gercek.txt")
        open(real, "w").write("x")
        os.symlink(real, os.path.join(self.root, "kisayol.txt"))
        self.assertEqual(files.resolve_upload_target(self.s, None, "kisayol.txt", overwrite=True), (real, None))
        self.assertEqual(files.resolve_upload_target(self.s, None, "kisayol.txt")[1], "exists")

    def test_write_upload_complete_and_atomic(self):
        dest = os.path.join(self.root, "a.bin")
        self.assertIsNone(files.write_upload(dest, io.BytesIO(b"abcdef"), 6, 4))
        self.assertEqual(open(dest, "rb").read(), b"abcdef")
        self.assertEqual(os.listdir(self.root), ["a.bin"])               # geçici dosya kalmaz

    def test_overwrite_keeps_mode(self):
        dest = os.path.join(self.root, "run.sh")
        open(dest, "w").write("old")
        os.chmod(dest, 0o755)
        self.assertIsNone(files.write_upload(dest, io.BytesIO(b"new"), 3, 4))
        self.assertEqual(os.stat(dest).st_mode & 0o777, 0o755)

    def test_incomplete_body_not_saved_and_existing_kept(self):
        dest = os.path.join(self.root, "a.bin")
        open(dest, "wb").write(b"ESKI")
        self.assertEqual(files.write_upload(dest, io.BytesIO(b"abc"), 10, 4), "incomplete")
        self.assertEqual(open(dest, "rb").read(), b"ESKI")                # üzerine yazma yarım kalmadı
        self.assertEqual(os.listdir(self.root), ["a.bin"])
        new = os.path.join(self.root, "b.bin")
        self.assertEqual(files.write_upload(new, io.BytesIO(b""), 5, 4), "incomplete")
        self.assertFalse(os.path.exists(new))

    def test_write_upload_replace_does_not_follow_symlink(self):
        victim = os.path.join(self.out, "victim.txt")
        open(victim, "w").write("ESKI")
        link = os.path.join(self.root, "l.txt")
        os.symlink(victim, link)                                          # savunma derinliği: resolve atlansa bile
        self.assertIsNone(files.write_upload(link, io.BytesIO(b"YENI"), 4, 4))
        self.assertEqual(open(victim).read(), "ESKI")


if __name__ == "__main__":
    unittest.main()

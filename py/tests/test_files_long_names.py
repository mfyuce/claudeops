"""write_upload/write_text geçici dosya adı hedef adını içermez: 255 baytlık adlar ENAMETOOLONG vermez (review cliops 2 Kas)."""
import io
import os
import tempfile
import unittest

from claudeops import files


class LongNames(unittest.TestCase):
    def test_upload_max_length_name(self):
        d = tempfile.mkdtemp()
        name = "a" * 255
        dest = os.path.join(d, name)
        self.assertIsNone(files.write_upload(dest, io.BytesIO(b"hi"), 2, 8))
        self.assertEqual(open(dest, "rb").read(), b"hi")
        self.assertEqual(os.listdir(d), [name])                         # tmp kalmadı
        self.assertEqual(files.write_upload(dest, io.BytesIO(b"x"), 1, 8, overwrite=False), "exists")
        self.assertEqual(os.listdir(d), [name])

    def test_tmp_name_short_and_unique(self):
        a = files._tmp_name("/x/" + "b" * 255, "upload")
        self.assertLess(len(os.path.basename(a)), 100)
        self.assertNotEqual(a, files._tmp_name("/x/" + "b" * 255, "upload"))


if __name__ == "__main__":
    unittest.main()


class BadEncoding(unittest.TestCase):
    def test_write_text_surrogate_leaves_no_tmp(self):
        from unittest import mock
        d = tempfile.mkdtemp()
        f = os.path.join(d, "a.txt")
        open(f, "w").write("x")
        with mock.patch.object(files, "_writable_roots", lambda s: [("project", d)]):
            r = files.write_text(None, f, "bad \ud800 text")
        self.assertEqual((r["ok"], r["error"]), (False, "bad_encoding"))
        self.assertEqual(os.listdir(d), ["a.txt"])
        self.assertEqual(open(f).read(), "x")


class RenameRaces(unittest.TestCase):
    def test_noreplace_dir_and_file(self):
        d = tempfile.mkdtemp()
        os.mkdir(os.path.join(d, "a")); os.mkdir(os.path.join(d, "b"))     # b BOŞ dizin: eskiden sessizce ezilirdi
        with self.assertRaises(FileExistsError):
            files._rename_noreplace(os.path.join(d, "a"), os.path.join(d, "b"))
        self.assertEqual(sorted(os.listdir(d)), ["a", "b"])
        open(os.path.join(d, "f"), "w").write("1"); open(os.path.join(d, "g"), "w").write("2")
        with self.assertRaises(FileExistsError):
            files._rename_noreplace(os.path.join(d, "f"), os.path.join(d, "g"))
        self.assertEqual(open(os.path.join(d, "g")).read(), "2")
        files._rename_noreplace(os.path.join(d, "f"), os.path.join(d, "h"))
        self.assertTrue(os.path.exists(os.path.join(d, "h")))

    def test_make_folder_race_is_exists(self):
        from unittest import mock
        d = tempfile.mkdtemp()
        real = os.mkdir
        def racing(p, *a, **k):
            real(p); raise FileExistsError(17, "x", p)
        with mock.patch.object(files, "_writable_roots", lambda s: [("project", d)]), mock.patch.object(files.os, "mkdir", racing):
            self.assertEqual(files.make_folder(None, d, "n")["error"], "exists")

    def test_rename_unlink_failure_keeps_one_name(self):
        from unittest import mock
        d = tempfile.mkdtemp()
        f = os.path.join(d, "f"); open(f, "w").write("x")
        real_unlink = os.unlink
        def unl(p, *a, **k):
            if p == f:
                raise PermissionError(13, "no", p)
            return real_unlink(p, *a, **k)
        with mock.patch.object(files, "_writable_roots", lambda s: [("project", d)]), mock.patch.object(files.os, "unlink", unl):
            r = files.rename_path(None, f, "g")
        self.assertFalse(r["ok"])
        self.assertEqual(sorted(os.listdir(d)), ["f"])

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


class RoundTrip(unittest.TestCase):
    def _save(self, raw, content):
        from unittest import mock
        d = tempfile.mkdtemp()
        f = os.path.join(d, "a.txt")
        open(f, "wb").write(raw)
        with mock.patch.object(files, "_writable_roots", lambda s: [("project", d)]):
            r = files.write_text(None, f, content)
        return r, open(f, "rb").read()

    def test_non_utf8_refused_and_untouched(self):
        r, data = self._save(b"abc \xff\xfe", "abc")
        self.assertEqual((r["ok"], r["error"]), (False, "bad_encoding"))
        self.assertEqual(data, b"abc \xff\xfe")

    def test_crlf_preserved(self):
        r, data = self._save(b"a\r\nb\r\n", "a\nx\n")
        self.assertTrue(r["ok"])
        self.assertEqual(data, b"a\r\nx\r\n")

    def test_lf_and_mixed_untouched(self):
        self.assertEqual(self._save(b"a\nb\n", "q\nw\n")[1], b"q\nw\n")
        self.assertEqual(self._save(b"a\r\nb\n", "q\nw\n")[1], b"q\nw\n")

    def test_upload_strips_setuid(self):
        d = tempfile.mkdtemp()
        f = os.path.join(d, "x")
        open(f, "w").write("1")
        os.chmod(f, 0o4755)
        self.assertIsNone(files.write_upload(f, io.BytesIO(b"2"), 1, 8))
        self.assertEqual(os.stat(f).st_mode & 0o7777, 0o755)


class WebMapping(unittest.TestCase):
    def test_bad_encoding_has_error_template(self):
        from claudeops.commands import web
        body, status = web._files_mutation_err("tr", "p", "a.txt", {"ok": False, "error": "bad_encoding", "detail": "x"})
        self.assertEqual(status, 400)
        self.assertIn("UTF-8", body["error"])

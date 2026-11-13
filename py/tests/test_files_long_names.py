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

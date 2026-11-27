"""TBD#374 (a) S3: model alanı TSV'ye sahte satır yazamaz."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


class _Tmp(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.d = d.name

    def patch(self, obj, name, value):
        p = mock.patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)


class RegisterRejectsControlChars(_Tmp):
    def setUp(self):
        super().setUp()
        self.patch(web, "ROSTER_TSV", os.path.join(self.d, "roster.tsv"))
        self.patch(web, "MODELS_TSV", os.path.join(self.d, "models.tsv"))
        self.patch(web, "find_sessions", lambda **k: [])
        self.patch(web.inst_mod, "get_instance", lambda name: None)

    def _files(self):
        return [os.path.exists(web.ROSTER_TSV), os.path.exists(web.MODELS_TSV)]

    def test_s3_register_model_with_newline_or_tab(self):
        for bad in ("m\nsahte\t/etc", "a\tb", "a\rb"):
            with self.subTest(bad=bad):
                res = web._register_project("zza", self.d, bad, lang="en")
                self.assertFalse(res["ok"])
                self.assertEqual(res["error"], "model contains invalid characters")
                self.assertEqual(self._files(), [False, False])

    def test_s3_edit_model_with_newline(self):
        self.assertTrue(web._register_project("zza", self.d, "m")["ok"])
        with open(web.ROSTER_TSV, encoding="utf-8") as f:
            before = f.read()
        res = web._edit_project("zza", "zza", self.d, "m\nsahte\t/etc", lang="en")
        self.assertEqual(res.get("error"), "model contains invalid characters")
        with open(web.ROSTER_TSV, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)


if __name__ == "__main__":
    unittest.main()

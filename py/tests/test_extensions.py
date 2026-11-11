"""Çekirdek genişleme noktası: reviewer mercek kaydı + `claudeops_enterprise` yükleyici. Paket YOKKEN davranış bugünküyle AYNI.
Tüm testler kayıt durumunu izole eder (global LENSES/_LENS_TEXT/_STATE geri alınır)."""
import copy
import os
import re
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import extensions as ext, review as rv  # noqa: E402


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._lenses, self._text = rv.LENSES, dict(rv._LENS_TEXT)
        self._extra, self._state = dict(rv._LENS_FORMAT_EXTRA), copy.deepcopy(ext._STATE)
        self._mod = sys.modules.get(ext.PACKAGE)
        rv.LENSES, ext._STATE["lenses"], ext._STATE["loaded"] = ("dry",), [], False
        rv._LENS_TEXT.clear(); rv._LENS_TEXT.update({k: v for k, v in self._text.items() if k[0] == "dry"})
        rv._LENS_FORMAT_EXTRA.clear()

    def tearDown(self):
        rv.LENSES = self._lenses
        rv._LENS_TEXT.clear(); rv._LENS_TEXT.update(self._text)
        rv._LENS_FORMAT_EXTRA.clear(); rv._LENS_FORMAT_EXTRA.update(self._extra)
        ext._STATE.clear(); ext._STATE.update(self._state)
        if self._mod is None:
            sys.modules.pop(ext.PACKAGE, None)
        else:
            sys.modules[ext.PACKAGE] = self._mod


class RegistryTest(_Isolated):
    def test_register_adds_lens_and_prompt(self):
        rv.register_lens("perf", "SADECE performans.", "ONLY performance.", " EK-TR", " EK-EN")
        self.assertEqual(rv.lenses(), ("dry", "perf"))
        tr = rv.build_review_prompt("p", "/w", "tr", "perf")
        self.assertIn("SADECE performans.", tr)
        self.assertTrue(tr.endswith(" EK-TR"))
        self.assertNotIn("Ayrıca: <yol:satır>", tr)
        self.assertNotIn("Gerçek kusurları bul", tr)

    def test_invalid_and_duplicate_rejected(self):
        for bad in ("", "Dry", "1x", "a b", "x" * 30, None):
            with self.assertRaises(ValueError):
                rv.register_lens(bad, "t", "e")
        with self.assertRaises(ValueError):
            rv.register_lens("dry", "t", "e")
        with self.assertRaises(ValueError):
            rv.register_lens("ok", "", "e")
        self.assertEqual(rv.lenses(), ("dry",))

    def test_builtin_dry_prompt_unchanged(self):
        tr = rv.build_review_prompt("p", "/w", "tr", "dry")
        self.assertIn("Ayrıca: <yol:satır>", tr)


class LoaderTest(_Isolated):
    def _fake(self, **attrs):
        m = types.ModuleType(ext.PACKAGE)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[ext.PACKAGE] = m
        return m

    def test_absent_is_silent_and_behaviour_unchanged(self):
        before = rv.build_review_prompt("p", "/w", "tr", "dry")
        with mock.patch.object(ext.importlib, "import_module", side_effect=ModuleNotFoundError("x", name=ext.PACKAGE)):
            st = ext.load(force=True)
        self.assertEqual((st["status"], st["detail"], st["lenses"]), ("absent", "", []))
        self.assertEqual(rv.lenses(), ("dry",))
        self.assertEqual(rv.build_review_prompt("p", "/w", "tr", "dry"), before)
        with self.assertRaises(ValueError):
            rv.build_review_prompt("p", "/w", "tr", "security")        # paket yok: yalnız dry

    def test_loaded_registers(self):
        self._fake(register=lambda api: api.register_lens("sec", "T", "E"), REQUIRES_CORE_API=ext.EXTENSION_API_VERSION, __version__="9")
        st = ext.load(force=True)
        self.assertEqual((st["status"], st["lenses"]), ("loaded", ["sec"]))
        self.assertIn("sec", rv.lenses())
        ext.load(force=True)                                          # tekrar yükleme: idempotent
        self.assertEqual(rv.lenses(), ("dry", "sec"))

    def test_incompatible_api_refused(self):
        self._fake(register=lambda api: api.register_lens("sec", "T", "E"), REQUIRES_CORE_API=ext.EXTENSION_API_VERSION + 1)
        with mock.patch.object(ext, "_log") as lg:
            st = ext.load(force=True)
        self.assertEqual(st["status"], "incompatible")
        self.assertEqual(rv.lenses(), ("dry",))
        lg.assert_called()

    def test_register_error_does_not_crash_core(self):
        def boom(api):
            raise RuntimeError("kırık")
        self._fake(register=boom)
        with mock.patch.object(ext, "_log"):
            st = ext.load(force=True)
        self.assertEqual(st["status"], "error")
        self.assertIn("kırık", st["detail"])

    def test_package_with_missing_dependency_is_reported_not_silent(self):
        with mock.patch.object(ext.importlib, "import_module", side_effect=ModuleNotFoundError("yok", name="baska_paket")), \
                mock.patch.object(ext, "_log") as lg:
            st = ext.load(force=True)
        self.assertEqual(st["status"], "error")
        lg.assert_called()

    def test_cannot_override_builtin_from_extension(self):
        self._fake(register=lambda api: api.register_lens("dry", "T", "E"))
        with mock.patch.object(ext, "_log"):
            st = ext.load(force=True)
        self.assertEqual(st["status"], "error")
        self.assertIn("Ayrıca: <yol:satır>", rv.build_review_prompt("p", "/w", "tr", "dry"))


class OneWayDependencyTest(unittest.TestCase):
    def test_core_never_imports_enterprise_directly(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "claudeops")
        pat = re.compile(r"^\s*(?:from|import)\s+claudeops_enterprise\b", re.M)
        bad = []
        for d, _, files in os.walk(root):
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(d, f), encoding="utf-8") as fh:
                        if pat.search(fh.read()):
                            bad.append(os.path.join(d, f))
        self.assertEqual(bad, [])        # yalnız importlib adıyla (extensions.py) yüklenir


if __name__ == "__main__":
    unittest.main()

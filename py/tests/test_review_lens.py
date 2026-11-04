"""Review merceği (lens=dry): istem, rapor yolu, çift anahtarı, elle koşu doğrulaması. Gerçek Popen/ağ YOK."""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402
from claudeops.commands import web_review  # noqa: E402

T = rv.ReviewTarget("evren", "glm-4.6", "glm-4.6")
TD = rv.ReviewTarget("evren", "glm-4.6", "glm-4.6", lens="dry")


class LensPromptTest(unittest.TestCase):
    def test_default_prompt_unchanged(self):
        self.assertEqual(rv.build_review_prompt("p", "/w", "tr"), rv.build_review_prompt("p", "/w", "tr", ""))
        self.assertIn("Gerçek kusurları bul", rv.build_review_prompt("p", "/w", "tr"))
        self.assertNotIn("DRY", rv.build_review_prompt("p", "/w", "en"))

    def test_dry_prompt_both_langs(self):
        tr = rv.build_review_prompt("p", "/w", "tr", "dry")
        en = rv.build_review_prompt("p", "/w", "en", "dry")
        self.assertIn("DRY", tr)
        self.assertIn("Ayrıca: <yol:satır>", tr)
        self.assertNotIn("Gerçek kusurları bul", tr)
        self.assertIn("DRY", en)
        self.assertIn("Also at: <path:line>", en)
        self.assertNotIn("Find real defects", en)
        for s in (tr, en):
            self.assertIn("## R-1 | P2 |", s)        # başlık biçimi aynı
            self.assertIn("reviews/", s)             # salt-okunur/yasak kuralları korunur

    def test_unknown_lens_raises(self):
        with self.assertRaises(ValueError):
            rv.build_review_prompt("p", "/w", "tr", "nope")


class LensPathKeyTest(unittest.TestCase):
    def test_path_has_lens_layer(self):
        d = rv.review_path("/r", "proj", TD, "20261105120000", "low")
        self.assertEqual(d, "/r/proj/evren/glm-4.6/low/dry/20261105120000/20261105120000.md")
        d0 = rv.review_path("/r", "proj", T, "20261105120000")
        self.assertEqual(d0, "/r/proj/evren/glm-4.6/20261105120000/20261105120000.md")

    def test_pair_key_separate(self):
        self.assertNotEqual(rv.pair_key("p", T), rv.pair_key("p", TD))
        self.assertEqual(rv.pair_key("p", T), "p|evren/glm-4.6")
        self.assertEqual(rv.pair_key("p", TD), "p|evren/glm-4.6~dry")

    def test_lens_never_in_planner_targets(self):
        self.assertEqual(T.lens, "")             # havuz/planlayıcı hedefleri lenssiz


class ManualRunLensTest(unittest.TestCase):
    def test_bad_lens_rejected_before_anything(self):
        cfg = SimpleNamespace(enabled=True)
        r = web_review.manual_run(cfg, "proj", "evren", "glm-4.6", "bogus")
        self.assertFalse(r["ok"])
        self.assertIn("lens", r["error"])


if __name__ == "__main__":
    unittest.main()

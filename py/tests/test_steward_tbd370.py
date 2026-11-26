"""TBD#370 (c): değnekçi saf çekirdeğindeki düzeltmeler (stdlib unittest; G/Ç yok)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import settings as settings_mod  # noqa: E402
from claudeops import steward as sw  # noqa: E402


class TrailingNewlineNameTest(unittest.TestCase):
    """`^...$` + `match` sondaki tek satır sonunu geçiriyordu; `"default\\n"` rezerve listesini aşıyordu."""

    def test_valid_name(self):
        for name in ("ab", "ancient-script-pipeline-fd", "a" * 47):
            self.assertTrue(sw.valid_name(name), repr(name))
            self.assertFalse(sw.valid_name(name + "\n"), repr(name))

    def test_valid_custom_id(self):
        self.assertTrue(sw.valid_custom_id("iso"))
        for sid in ("iso\n", "default\n", "all\n", "services\n", "degnekci\n", "ab\r\n"):
            self.assertFalse(sw.valid_custom_id(sid), repr(sid))

    def test_valid_steward_id(self):
        self.assertTrue(sw.valid_steward_id("default"))
        self.assertTrue(sw.valid_steward_id("iso"))
        for sid in ("default\n", "iso\n", "all\n"):
            self.assertFalse(sw.valid_steward_id(sid), repr(sid))

    def test_reviewer_ids(self):
        role = {"role": "reviewer"}
        st = {"stewards": {"reviewer": role, "iso\n": role, "default\n": role}}
        with mock.patch.object(settings_mod, "load_settings", return_value=st):
            self.assertEqual(sw.reviewer_ids(), frozenset({"reviewer"}))


class ConfirmedMentionTest(unittest.TestCase):
    """Düzyazıdaki `STEWARD-DONE-CONFIRMED` anması teyit sayılmaz; gerçek teyit biçimleri sayılır."""

    EV = "abc1234 kalan açık iş 0, testler yeşil"

    def confirmed(self, text):
        return sw.scan_markers(text)["confirmed"]

    def test_mention_is_not_a_confirmation(self):
        for text in (
                "STEWARD-DONE-CONFIRMED yazmıyorum, TODO'da 9 açık iş var",
                "STEWARD-DONE-CONFIRMED yazmıyorum:** TODO'da 9 açık `- [ ]` iş var",
                "**STEWARD-DONE-CONFIRMED yazmıyorum, çünkü kapsamdaki üç parça açık.**",
                "`STEWARD-DONE-CONFIRMED` yazmıyorum, iş kaldı",
                "Açık iş var; STEWARD-DONE-CONFIRMED yazmıyorum.",
                "STEWARD-DONE: tamam (91938e5); kalan 0 değil, STEWARD-DONE-CONFIRMED yazmıyorum.",
                "STEWARD-DONE-CONFIRMED sonrası TODO.md'de 1 açık madde sorusu çözüldü (e80e77e), açık iş 0.",
                "zlkrn: STEWARD-DONE-CONFIRMED geldi ama TODO.md'de 168 açık madde var",
                "Sonra STEWARD-DONE-CONFIRMED abc1234 kalan 0 yazacağım",
                "STEWARD-DONE-CONFIRMED için abc1234 sonrası 0 madde kalmalı",
                "STEWARD-DONE-CONFIRMED (henüz değil)"):
            m = sw.scan_markers(text)
            self.assertIsNone(m["confirmed"], text)
            self.assertFalse(m["done"], text)

    def test_mention_does_not_overwrite_real_confirmation(self):
        text = f"STEWARD-DONE-CONFIRMED: {self.EV}\nSTEWARD-DONE-CONFIRMED yazmadan önce TODO'ya baktım."
        self.assertEqual(self.confirmed(text), self.EV)

    def test_colon_forms_still_count(self):
        for text, body in (
                (f"STEWARD-DONE-CONFIRMED: {self.EV}", self.EV),
                (f"- STEWARD-DONE-CONFIRMED: {self.EV}", self.EV),
                (f"STEWARD-DONE-CONFIRMED : {self.EV}", ": " + self.EV),
                (f"Son teyit: STEWARD-DONE-CONFIRMED: {self.EV}", self.EV),
                (f"İş bitti. STEWARD-DONE-CONFIRMED: {self.EV}", self.EV),
                (f"## STEWARD-DONE-CONFIRMED: {self.EV}", self.EV),
                (f"**STEWARD-DONE-CONFIRMED:** {self.EV}", "** " + self.EV),
                (f"**STEWARD-DONE-CONFIRMED**: {self.EV}", "**: " + self.EV),
                ("STEWARD-DONE-CONFIRMED:", ""),
                ("STEWARD-DONE-CONFIRMED: bitti", "bitti")):
            self.assertEqual(self.confirmed(text), body, text)

    def test_colonless_forms_still_count(self):
        for text, body in (
                (f"STEWARD-DONE-CONFIRMED {self.EV}", self.EV),
                (f"STEWARD-DONE-CONFIRMED — {self.EV}", "— " + self.EV),
                (f"STEWARD-DONE-CONFIRMED - {self.EV}", "- " + self.EV),
                (f"STEWARD-DONE-CONFIRMED `abc1234` kalan 0", "`abc1234` kalan 0"),
                (f"STEWARD-DONE-CONFIRMED (abc1234) kalan 0", "(abc1234) kalan 0"),
                (f"**STEWARD-DONE-CONFIRMED** {self.EV}", "** " + self.EV),
                (f"Teyit: STEWARD-DONE-CONFIRMED {self.EV}", self.EV),
                ("STEWARD-DONE-CONFIRMED", ""),
                ("**STEWARD-DONE-CONFIRMED**", "**"),
                ("STEWARD-DONE-CONFIRMED.", ".")):
            self.assertEqual(self.confirmed(text), body, text)


if __name__ == "__main__":
    unittest.main()

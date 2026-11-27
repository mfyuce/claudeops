"""27 Kas 2026 inceleme notları: işaret okuma düzeltmeleri (stdlib unittest; G/Ç yok)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402


class DoneThenWorkTest(unittest.TestCase):
    """`bitti, şimdi X`: "bitti" önceki işi anlatır, devamındaki iş kaybolmamalı."""

    WORK = ("bitti, şimdi testleri koş", "done; next: fix lint", "Bitti. Sıradaki iş: raporu yaz",
            "**bitti**, sırada F5 düzeltmesi", "done - now run the tests", "bitti; ŞİMDİ: eşlik koşusu",
            "done, then update the docs")
    NO_WORK = ("bitti, şimdi yok", "done; next: none", "done; next: -", "bitti, sıradaki: yok", "bitti, şimdi.",
               "done, now waiting", "bitti, şimdi bekliyorum", "bitti, sırada iş yok", "done, next: done",
               "done, nothing now", "bitti, kalanlar TBD'de", "bitti (devir yazıldı)", "bitti, şimdilik bu kadar",
               "done, nowhere else to go", "bitti, sonrası sahipte")

    def test_continuation_is_work(self):
        for v in self.WORK:
            with self.subTest(v):
                self.assertFalse(sw._is_no_work_value(v))
                self.assertEqual(sw.marker_next_work(f"Rapor.\nSTEWARD-NEXT: {v}"), v)
                self.assertFalse(sw.next_none_stated(f"Rapor.\nSTEWARD-NEXT: {v}"))
                self.assertEqual(sw.next_line(f"Rapor.\nsıradaki: {v}"), (True, v))

    def test_finished_without_work_stays_no_work(self):
        for v in self.NO_WORK:
            with self.subTest(v):
                self.assertTrue(sw._is_no_work_value(v))
                self.assertEqual(sw.marker_next_work(f"Rapor.\nSTEWARD-NEXT: {v}"), "")


class ConfirmColonMentionTest(unittest.TestCase):
    """`:` ile yazılmış olsa da "yazmıyorum" diyen satır teyit değildir (kanıt süzgecinden geçip projeyi kapatabiliyordu)."""

    DENIALS = ("yazmıyorum, iş sürüyor", "yazmıyorum; abc1234 sonrası 0 değil 3 iş var", "henüz yazamıyorum (abc1234, kalan 0 değil)",
               "Bunu YAZMAYACAĞIM: abc1234 0", "henüz değil, abc1234 sonrası 0 test eksik", "not yet, abc1234 leaves 0 reviews done",
               "I am not writing this; abc1234 0", "veremiyorum, abc1234 0", "** yazmadım, abc1234 0")
    CLAIMS = ("abc1234 kalan açık iş 0, kanıt", "abc1234 kalan açık iş 0, push yapılamadı değil, yapıldı",
              "kalan açık iş 0, son commit abc1234", "abc1234 kalan 0; STEWARD-NEXT yazmıyorum", "bitti", "")

    def test_denial_is_not_confirmation(self):
        for body in self.DENIALS:
            for text in (f"STEWARD-DONE-CONFIRMED: {body}", f"**STEWARD-DONE-CONFIRMED**: {body}"):
                with self.subTest(text):
                    self.assertIsNone(sw.scan_markers(text)["confirmed"])
                    self.assertFalse(sw.scan_markers(text)["done"])

    def test_claims_still_read(self):
        for body in self.CLAIMS:
            with self.subTest(body):
                self.assertEqual(sw.scan_markers(f"STEWARD-DONE-CONFIRMED: {body}")["confirmed"], body)


if __name__ == "__main__":
    unittest.main()

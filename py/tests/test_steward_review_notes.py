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


if __name__ == "__main__":
    unittest.main()

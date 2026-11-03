"""GATE-TODO4 madde 2: evren/ucli zaman asiminda akistaki ham metin `KISMI` basligiyla rapor dosyasina yazilir.
Gercek Popen YOK (NoRealReviewMixin, Base). Calistirma: python3 -m unittest discover -s py/tests"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_web_review_runner import Base, EV, SECRET  # noqa: E402
from claudeops import review as rv  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402


class TestTimeoutKismi(Base):
    def _run(self, **kw):
        self.cfg.review_timeout_minutes = 1
        with mock.patch.object(wr, "KILL_GRACE_SECONDS", 0.01), mock.patch.object(wr.os, "killpg"):
            self.ev(popen=self.popen(hang=True, **kw))
        return self.pair(EV)

    def test_streamed_text_without_heading_is_kept_with_kismi_header(self):
        rec = self._run(err="dosyalara bakiyorum\nhttp.py'de bir sorun gordum\n")
        self.assertEqual(rec["status"], "partial")
        self.assertIn("timeout", rec["error"])
        text = open(rec["file"]).read()
        self.assertTrue(text.startswith("# KISMI RAPOR"), text)
        self.assertIn("http.py'de bir sorun gordum", text)

    def test_kismi_text_is_masked(self):
        rec = self._run(err=f"anahtar {SECRET} burada\n")
        text = open(rec["file"]).read()
        self.assertNotIn(SECRET, text)
        self.assertIn("KISMI", text)

    def test_streamed_report_with_heading_still_preferred_and_parsed(self):
        rec = self._run(err="onsoz\n## R-1 | P2 | a.py:3 | Baslik\ngovde\n")
        text = open(rec["file"]).read()
        self.assertTrue(text.startswith("## R-1 | P2"), text)       # basliklisi KISMI sarmalamaz
        self.assertNotIn("KISMI", text)

    def test_no_stream_still_error(self):
        rec = self._run(err="")
        self.assertEqual(rec["status"], "error")
        self.assertFalse(rec.get("file"))

    def test_io_log_streamed_text_pure(self):
        lg = wr.IoLog(os.path.join(self.tmp, "x.io.jsonl"))
        self.assertEqual(lg.streamed_text(), "")
        lg.feed_err("merhaba\nikinci satir")
        self.assertEqual(lg.streamed_text(), "merhaba\nikinci satir")
        lg.close()


if __name__ == "__main__":
    unittest.main()

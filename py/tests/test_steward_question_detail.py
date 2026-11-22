"""STEWARD-DETAIL: soruya opsiyonel Markdown detay (panel/`/q` 'Detay' düğmesi)."""
import tempfile
import shutil
import unittest

from claudeops import steward as sw


class DetailTest(unittest.TestCase):
    def test_scan_and_actions(self):
        m = sw.scan_markers("STEWARD-ASK: Hangisi?\nSTEWARD-DETAIL: **Durum**\n- a\n- b\n\nSTEWARD-NEXT: x")
        self.assertEqual(m["details"], ["**Durum**\n- a\n- b"])
        acts = sw.marker_record_actions("p", "p", m)
        self.assertEqual(acts[0].payload["detail"], "**Durum**\n- a\n- b")

    def test_no_detail(self):
        acts = sw.marker_record_actions("p", "p", sw.scan_markers("STEWARD-ASK: Hangisi?"))
        self.assertNotIn("detail", acts[0].payload)

    def test_page_shows_detail(self):
        q = sw.Question(id="q1", project="p", text="s?", created_at=1.0, detail="<b>x</b>")
        h = sw.question_page_html(q, "tr", "ask", action="/q/q1")
        self.assertIn("Detay", h)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", h)
        self.assertNotIn("Detay", sw.question_page_html(sw.Question(id="q2", project="p", text="s?", created_at=1.0), "tr", "ask"))


if __name__ == "__main__":
    unittest.main()

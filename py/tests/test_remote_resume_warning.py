"""GATE-TODO4 madde 6: uzak baslatmada buyuk baglam --resume uyarisi (saf fonksiyon; host API'si gerektiren token sayimi yok).
Calistirma: python3 -m unittest discover -s py/tests"""
import os
import sys
import unittest
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class TestRemoteResumeWarning(unittest.TestCase):
    def test_warns_when_not_fresh_and_limit_on(self):
        w = ws.remote_resume_warning("ysf", "h1", False, NS(resume_max_context_tokens=150000))
        self.assertIn("ysf@h1", w)
        self.assertIn("150000", w)
        self.assertIn("fresh=True", w)

    def test_no_warning_when_fresh(self):
        self.assertEqual(ws.remote_resume_warning("ysf", "h1", True, NS(resume_max_context_tokens=150000)), "")

    def test_no_warning_when_limit_off(self):
        self.assertEqual(ws.remote_resume_warning("ysf", "h1", False, NS(resume_max_context_tokens=0)), "")
        self.assertEqual(ws.remote_resume_warning("ysf", "h1", False, NS(resume_max_context_tokens=None)), "")


if __name__ == "__main__":
    unittest.main()

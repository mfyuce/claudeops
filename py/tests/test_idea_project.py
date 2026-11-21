"""Panel fikir kutusu proje seçici (TODO 538, 21 Kas): fikir oluşturulurken proje verilebilir; bilinmeyen proje reddedilir."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402


class IdeaProject(_Tmp):
    def test_idea_with_project_and_unknown_project(self):
        if True:
            sw.upsert_project("alpha", phase="planned")
            r = ws.http_idea({"text": "fikir a", "project": "alpha"})
            self.assertTrue(r["ok"])
            self.assertEqual(r["idea"]["project"], "alpha")
            self.assertEqual(r["idea"]["status"], "new")
            r = ws.http_idea({"text": "fikir b", "project": "yok"})
            self.assertEqual((r["ok"], r["error"]), (False, "unknown project"))
            r = ws.http_idea({"text": "fikir c"})
            self.assertEqual((r["ok"], r["idea"]["project"]), (True, ""))


if __name__ == "__main__":
    unittest.main()

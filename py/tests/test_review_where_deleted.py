"""TBD#400: silinen projeye gelen "nerede review edeyim?" cevabı projeyi yeniden yaratmaz."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudeops import steward as sw  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402


class ReviewWhereDeletedProjectTest(_Tmp):
    def setUp(self):
        super().setUp()
        self.paths = sw.paths_for("default")
        q = sw.Question(id="rq1", project="gone", text="nerede?", created_at=1.0, status="answered", answer="uzak")
        sw.save_questions([q], self.paths)
        self.q = q

    def test_deleted_project_is_not_recreated(self):
        sw.apply_review_where_answer(self.q, self.paths)
        self.assertNotIn("gone", sw.load_projects(self.paths))
        kept = sw.find_question("rq1", self.paths)
        self.assertEqual(kept.answer, "uzak")
        self.assertTrue(kept.delivered_at)
        failed = [e for e in sw.tail_log(20, self.paths) if e.get("event") == "review_where_failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].get("project"), "gone")

    def test_existing_project_still_gets_the_answer(self):
        sw.save_projects({"gone": sw.Project(name="gone", phase="planned", review_where="ask")}, self.paths)
        sw.apply_review_where_answer(self.q, self.paths)
        self.assertEqual(sw.load_projects(self.paths)["gone"].review_where, "remote")


if __name__ == "__main__":
    unittest.main()

"""Tireli proje adları (yuhem `ancient-script-pipeline-fd`)."""
import unittest

from claudeops import steward as sw
from steward_testlib import _Tmp

NAME = "ancient-script-pipeline-fd"


class ValidNameTest(unittest.TestCase):
    def test_hyphen_rules(self):
        for ok in (NAME, "a-b", "a_b-c2", "ncs", "cops31ulak"):
            self.assertTrue(sw.valid_name(ok), ok)
        for bad in ("-a", "a-", "a--b", "A-b", "a/b", "a-.b", "../a", "1-a", "", "a" * 49):
            self.assertFalse(sw.valid_name(bad), bad)


class HyphenProjectTest(_Tmp):
    def test_store_and_session_mapping(self):
        sw.upsert_project(NAME, phase="planned")
        projects = sw.load_projects()
        self.assertIn(NAME, projects)
        self.assertEqual(sw._project_key(NAME + "20261118", projects), NAME)
        self.assertEqual(sw._project_key(NAME + "20261118_2", projects), NAME)
        self.assertEqual(sw._project_key("ancient-script-pipeline20261118", projects), "")
        self.assertIn(NAME, sw.ownership_index()["owners"])

    def test_shorter_prefix_does_not_claim(self):
        sw.upsert_project("ancient")
        self.assertEqual(sw._project_key(NAME + "20261118", sw.load_projects()), "")


if __name__ == "__main__":
    unittest.main()

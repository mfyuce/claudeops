import unittest
from claudeops.commands import web_steward


class TodoDoneReTest(unittest.TestCase):
    def test_done_word_matches(self):
        self.assertTrue(web_steward._TODO_DONE_RE.search("- iş DONE bitti"))
        self.assertFalse(web_steward._TODO_DONE_RE.search("- abandoned work"))


if __name__ == "__main__":
    unittest.main()

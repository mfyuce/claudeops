import unittest

from claudeops.commands import watch


class ContextTextTests(unittest.TestCase):
    def test_with_threshold(self):
        d = {"sessions": {"a": {"context_tokens": 120000, "context_warn": 300000}}}
        self.assertEqual(watch.context_text_from_facts(d, "a"), "ctx 120K/300K %40")

    def test_without_threshold(self):
        d = {"sessions": {"a": {"context_tokens": 120000}}}
        self.assertEqual(watch.context_text_from_facts(d, "a"), "ctx 120K")

    def test_unknown(self):
        for d in ({}, None, {"sessions": {"a": {"context_tokens": None}}}, {"sessions": {}}):
            self.assertEqual(watch.context_text_from_facts(d, "a"), "")

    def test_caps_at_100(self):
        d = {"sessions": {"a": {"context_tokens": 400000, "context_warn": 300000}}}
        self.assertTrue(watch.context_text_from_facts(d, "a").endswith("%100"))


if __name__ == "__main__":
    unittest.main()

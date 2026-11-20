import unittest
from claudeops.commands import web_hosts


class OrphanBriefTest(unittest.TestCase):
    def test_brief(self):
        self.assertEqual(web_hosts._orphan_brief({"servers": 2, "procs": "3", "detail": {"x": 1}, "last_end": 5}),
                         {"servers": 2, "procs": 3, "last_end": 5})
        self.assertIsNone(web_hosts._orphan_brief(None))
        self.assertIsNone(web_hosts._orphan_brief({"servers": "x"}))


if __name__ == "__main__":
    unittest.main()

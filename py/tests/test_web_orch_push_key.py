"""`web_orch._push_result` anahtarı host içerir: farklı host'taki aynı adlı katılımcılar çakışmaz (stdlib unittest).

Çalıştırma:  python3 py/tests/test_web_orch_push_key.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_orch  # noqa: E402


class PushKeyTest(unittest.TestCase):
    def setUp(self):
        web_orch._WAITING.clear()
        web_orch._PUSHED.clear()
        self.addCleanup(web_orch._WAITING.clear)
        self.addCleanup(web_orch._PUSHED.clear)

    def test_same_name_two_hosts_do_not_collide(self):
        web_orch._WAITING.update({("r1", "a", "w"), ("r1", "b", "w")})
        self.assertTrue(web_orch._push_result("r1", "w", "ok", "x", host="b"))
        self.assertIn(("r1", "b", "w"), web_orch._PUSHED)
        self.assertNotIn(("r1", "a", "w"), web_orch._PUSHED)

    def test_without_host_ambiguous_is_rejected(self):
        web_orch._WAITING.update({("r1", "a", "w"), ("r1", "b", "w")})
        self.assertFalse(web_orch._push_result("r1", "w", "ok", "x"))
        self.assertEqual(web_orch._PUSHED, {})

    def test_without_host_single_match_accepted(self):
        web_orch._WAITING.add(("r1", "a", "w"))
        self.assertTrue(web_orch._push_result("r1", "w", "ok", "x"))
        self.assertIn(("r1", "a", "w"), web_orch._PUSHED)

    def test_wrong_host_rejected(self):
        web_orch._WAITING.add(("r1", "a", "w"))
        self.assertFalse(web_orch._push_result("r1", "w", "ok", "x", host="zzz"))


if __name__ == "__main__":
    unittest.main()

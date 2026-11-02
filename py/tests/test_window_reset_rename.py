"""TBD#33: "Sıfırla + yeniden adlandır" (window_actions.run_action new_name=). Çalıştırma: python3 py/tests/test_window_reset_rename.py -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import window_actions as wa  # noqa: E402
from test_window_actions import PanelCase, row, status, TOKEN  # noqa: E402


class CheckNewNameTests(unittest.TestCase):
    def test_valid(self):
        wa.check_new_name("yeni")

    def test_invalid(self):
        for bad in ("", "Yeni", "ab1", "a_1", "a b", "../x", "a-b"):
            with self.assertRaises(ValueError, msg=bad):
                wa.check_new_name(bad)


class ResetRenameTests(PanelCase):
    def run_act(self, panel, action, name="ae", host="local", new_name=""):
        client = wa.PanelClient(panel.port, lambda: TOKEN)
        return wa.run_action(client, action, host, name, new_name=new_name)
    def test_rename_starts_fresh_under_new_name_after_stop(self):
        p = self.serve(status([row("ae")]))
        r = self.run_act(p, "reset", name="ae", new_name="be")
        self.assertTrue(r.ok, r.text if hasattr(r, "text") else r)
        posts = p.posts()
        self.assertEqual([x[0] for x in posts], ["/api/stop", "/api/start"])
        self.assertEqual(posts[1][1]["name"], "be")
        self.assertTrue(posts[1][1]["fresh"])

    def test_invalid_name_refused_before_stop(self):
        p = self.serve(status([row("ae")]))
        r = self.run_act(p, "reset", name="ae", new_name="Bad1")
        self.assertFalse(r.ok)
        self.assertEqual(p.posts(), [])

    def test_new_name_only_with_reset(self):
        p = self.serve(status([row("ae")]))
        r = self.run_act(p, "restart", name="ae", new_name="be")
        self.assertFalse(r.ok)
        self.assertEqual(p.posts(), [])

    def test_plain_reset_keeps_name(self):
        p = self.serve(status([row("ae")]))
        self.run_act(p, "reset", name="ae")
        self.assertEqual(p.posts()[-1][1]["name"], "ae")


if __name__ == "__main__":
    unittest.main()

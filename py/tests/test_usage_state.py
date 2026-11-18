"""`usage_state.py`: tek kaynak kullanım durumu (yazma, bayatlık, başarısız okumada eski değeri koruma)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import usage_state as us  # noqa: E402


class UsageStateTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(us, "STATE_PATH", os.path.join(tempfile.mkdtemp(), "usage_state.json"))
        p.start()
        self.addCleanup(p.stop)

    def test_empty_is_stale(self):
        g = us.get(1000.0)
        self.assertTrue(g["stale"])
        self.assertEqual(g["providers"], {})
        self.assertIsNone(us.provider("agy"))

    def test_set_get_fresh_then_stale_after_10_min(self):
        us.set_all({"agy": {"supported": True, "available": True, "entries": [1]}}, now=1000.0, source="t")
        g = us.get(1100.0)
        self.assertFalse(g["stale"])
        self.assertEqual(g["providers"]["agy"]["age_secs"], 100)
        self.assertFalse(g["providers"]["agy"]["stale"])
        self.assertTrue(us.get(1000.0 + 601)["providers"]["agy"]["stale"])
        self.assertEqual(oct(os.stat(us.STATE_PATH).st_mode & 0o777), "0o600")

    def test_failed_read_keeps_last_good_entries_and_old_ok_at(self):
        us.set_all({"agy": {"supported": True, "available": True, "entries": ["x"]}}, now=1000.0)
        us.set_all({"agy": {"supported": True, "available": False, "reason": "parse_failed"}}, now=2000.0)
        r = us.get(2100.0)["providers"]["agy"]
        self.assertFalse(r["available"])
        self.assertEqual(r["entries"], ["x"])           # eski değer korunur ama
        self.assertTrue(r["stale_data"])
        self.assertEqual(r["age_secs"], 1100)           # yaşı eski başarılı okumadan sayılır
        us.set_all({"claude": {"supported": True, "available": False, "reason": "no_running_session"}}, now=2200.0)
        c = us.get(2300.0)["providers"]["claude"]
        self.assertTrue(c["stale"])                     # hiç başarılı okuma yok
        self.assertIsNone(c["age_secs"])


if __name__ == "__main__":
    unittest.main()


class AccountCli(unittest.TestCase):
    def test_render_account_marks_stale_and_unreadable(self):
        from claudeops.commands import usage as u
        d = {"at": 1, "age_secs": 700, "stale": True, "source": "periodic", "providers": {
            "agy": {"supported": True, "available": True, "age_secs": 100, "stale": False,
                    "entries": [{"label": "Gemini Models — Weekly Limit Remaining", "percent": "69", "detail": "Resets X"}]},
            "copilot": {"supported": True, "available": False, "reason": "no_running_session", "stale": True},
            "shell": {"supported": False}}}
        t = u.render_account(d)
        self.assertIn("[BAYAT]", t.splitlines()[0])
        self.assertIn("Weekly Limit Remaining: 69% Resets X", t)
        self.assertIn("copilot: okunamadı (no_running_session) [BAYAT]", t)
        self.assertIn("shell: desteklenmiyor", t)

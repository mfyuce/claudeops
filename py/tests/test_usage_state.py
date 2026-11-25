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

    def test_cached_view_reads_state_without_polling(self):
        from claudeops.commands import web
        v = web.usage_cached_view()
        self.assertTrue(v["ok"] and v["cached"] and v["stale"])
        self.assertEqual(v["providers"], {})
        with mock.patch.object(web, "_usage_all", side_effect=AssertionError("okuma yapmamalı")):
            us.set_all({"agy": {"supported": True, "available": True, "entries": [1]}}, source="periodic")
            v = web.usage_cached_view()
        self.assertEqual(v["source"], "periodic")
        self.assertIn("agy", v["providers"])
        self.assertFalse(v["stale"])
        self.assertIsNotNone(v["age_secs"])

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

    def test_auth_backoff_expires_and_ignores_other_failures(self):
        us.set_all({"agy": {"supported": True, "available": False, "reason": "auth_required"},
                    "claude": {"supported": True, "available": False, "reason": "read_failed"}}, now=1000.0)
        self.assertEqual(us.auth_backoff(1000.0 + 300), {"agy"})
        self.assertEqual(us.auth_backoff(1000.0 + us.AUTH_RETRY_SECONDS), set())
        us.set_all({"agy": {"supported": True, "available": True, "entries": [1]}}, now=1400.0)
        self.assertEqual(us.auth_backoff(1500.0), set())

    def test_periodic_and_tick_skip_logged_out_cli_but_button_reads_it(self):
        from claudeops.commands import web
        us.set_all({"agy": {"supported": True, "available": False, "reason": "auth_required"}})
        with mock.patch.object(web, "_usage_all", return_value={"ok": True, "providers": {}}) as read:
            res = web.usage_refresh(source="periodic")
            only = read.call_args.args[0]
            self.assertEqual(res["auth_backoff"], ["agy"])
            self.assertNotIn("agy", only)
            self.assertTrue({"claude", "api"} <= only)
            web._usage_collect_store({"agy", "claude"})
            self.assertEqual(read.call_args.args[0], {"claude"})
            web.usage_refresh(source="panel")
            self.assertIsNone(read.call_args.args[0])


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

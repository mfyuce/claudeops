"""D2: başarısız yerel başlatmadan sonra üstel geri çekilme (10 dk / 1 sa / 6 sa); big-context günlüğü yalnız gerçek başlatmada."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.commands import web_steward as ws  # noqa: E402


class BackoffMath(unittest.TestCase):
    def setUp(self):
        ws._START_FAILS.clear()
        self.addCleanup(ws._START_FAILS.clear)

    def test_steps_and_reset(self):
        self.assertEqual(ws._start_backoff_remaining("p", 1000.0), 0.0)
        ws._start_backoff_note("p", False, now=1000.0)
        self.assertEqual(ws._start_backoff_remaining("p", 1100.0), 500.0)           # 10 dk
        ws._start_backoff_note("p", False, now=2000.0)
        self.assertEqual(ws._start_backoff_remaining("p", 2000.0), 3600.0)          # 1 sa
        ws._start_backoff_note("p", False, now=3000.0)
        ws._start_backoff_note("p", False, now=4000.0)
        self.assertEqual(ws._start_backoff_remaining("p", 4000.0), 21600.0)         # 6 sa tavan
        ws._start_backoff_note("p", True)
        self.assertEqual(ws._start_backoff_remaining("p", 4000.0), 0.0)


class EnsureRunningBackoff(unittest.TestCase):
    def setUp(self):
        ws._START_FAILS.clear()
        self.addCleanup(ws._START_FAILS.clear)
        self.events = []
        for p in (mock.patch.object(ws, "_live_sessions", lambda n, sid="default": []),
                  mock.patch.object(ws, "_model_endpoint_mismatch", lambda n: None),
                  mock.patch.object(ws, "_api_blocked", lambda n: None),
                  mock.patch.object(ws, "_closed_in_models", lambda n: False),
                  mock.patch.object(ws, "_resume_lacks_ho", lambda n, c: ""),
                  mock.patch.object(ws, "_oversized_resume", lambda n, c: 400000),
                  mock.patch.object(ws, "_launch_kwargs", lambda n, m, e: {}),
                  mock.patch.object(ws.sw, "log_event", lambda ev, **k: self.events.append(ev))):
            p.start()
            self.addCleanup(p.stop)

    def test_failed_start_backs_off_and_logs_no_big_context(self):
        with mock.patch.object(ws, "_act", return_value={"ok": False, "error": "x"}) as act:
            r1 = ws._ensure_running("vc")
            r2 = ws._ensure_running("vc")
        self.assertFalse(r1["ok"])
        self.assertEqual(r2["code"], "start_backoff")
        self.assertEqual(act.call_count, 1)                       # ikinci çağrı spawn denemedi
        self.assertNotIn("start_fresh_big_context", self.events)  # gerçek başlatma olmadı

    def test_success_logs_big_context_and_clears(self):
        with mock.patch.object(ws, "_act", return_value={"ok": True}), \
                mock.patch.object(ws, "_start_appeared", lambda n, s: True), \
                mock.patch.object(ws, "_wait_ready", lambda n, c: True), \
                mock.patch.object(ws, "_project_cli", lambda n: "claude"):
            r = ws._ensure_running("vc")
        self.assertTrue(r["ok"])
        self.assertIn("start_fresh_big_context", self.events)


if __name__ == "__main__":
    unittest.main()

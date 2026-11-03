"""GATE-TODO4 madde 5: `start` 'ok' donunce oturum gercekten gorunmeli; gorunmezse hata (gercek tmux/uyku yok).
Calistirma: python3 -m unittest discover -s py/tests"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class StartAppearsTest(unittest.TestCase):
    def test_appears_after_a_few_polls(self):
        calls = {"n": 0}

        def live(name, sid="default"):
            calls["n"] += 1
            return [object()] if calls["n"] >= 3 else []
        slept = []
        with mock.patch.object(ws, "_live_sessions", live):
            self.assertTrue(ws._start_appeared("p", timeout=5, sleep=slept.append))
        self.assertEqual(len(slept), 2)

    def test_never_appears_returns_false_without_real_sleep(self):
        slept = []
        with mock.patch.object(ws, "_live_sessions", lambda n, s="default": []):
            self.assertFalse(ws._start_appeared("p", timeout=1.0, sleep=slept.append))
        self.assertEqual(len(slept), 2)      # 1.0 / 0.5

    def test_cache_is_invalidated_each_poll(self):
        inv = []
        with mock.patch.object(ws, "_live_sessions", lambda n, s="default": []), \
                mock.patch.object(ws, "_scan_invalidate", lambda: inv.append(1)):
            ws._start_appeared("p", timeout=1.0, sleep=lambda s: None)
        self.assertEqual(len(inv), 3)

    def test_ensure_running_errors_when_ok_but_no_session(self):
        ws.configure(start=lambda *a, **k: {"ok": True})
        with mock.patch.object(ws, "_live_sessions", lambda n, s="default": []), \
                mock.patch.object(ws, "_oversized_resume", lambda n, c: 0), \
                mock.patch.object(ws, "steward_config", lambda sid="default": mock.MagicMock()), \
                mock.patch.object(ws, "_start_appeared", lambda n, s="default": False), \
                mock.patch.object(ws, "_wait_ready", lambda n, c: self.fail("must not wait")):
            res = ws._ensure_running("p")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "start_not_visible")


if __name__ == "__main__":
    unittest.main()

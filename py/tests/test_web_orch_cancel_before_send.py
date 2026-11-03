"""860: iptal edilmiş run'da `_run_turn` prompt'u ENJEKTE etmez, status=cancelled döner (hepsi sahte; ağ/süreç YOK)."""
import os
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_orch  # noqa: E402


class CancelBeforeSendTest(unittest.TestCase):
    def _run(self, cancelled):
        p = SimpleNamespace(role="worker", host="local", name="w1", cli="claude")
        s = SimpleNamespace(name="w1", cli="claude", cwd="/x", sid="abc")
        ev = threading.Event()
        if cancelled:
            ev.set()
        with mock.patch.object(web_orch, "get_provider", lambda c: mock.MagicMock()), \
                mock.patch.object(web_orch, "_fetch_exchange", lambda *a, **k: {"assistant": ""}), \
                mock.patch.object(web_orch, "_send_prompt", return_value=False) as send, \
                mock.patch.object(web_orch, "diag_log"):
            res = web_orch._run_turn(p, 1, "worker_result", {("local", "w1"): s}, "hi", 1.0, ev, "M", "r1")
        return res, send

    def test_cancelled_run_sends_nothing(self):
        res, send = self._run(True)
        self.assertEqual(res.status, "cancelled")
        send.assert_not_called()

    def test_live_run_still_sends(self):
        res, send = self._run(False)
        send.assert_called_once()
        self.assertNotEqual(res.status, "cancelled")

    def test_waiting_key_is_cleaned_after_cancel(self):
        self._run(True)
        self.assertNotIn(("r1", "local", "w1"), web_orch._WAITING)


if __name__ == "__main__":
    unittest.main()

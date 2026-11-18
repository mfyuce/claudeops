"""Uzak yanıt beklemede kalıcı hata (401/403/404) ilk poll'da vazgeçirir; geçici hata eşik (5) kadar denenir (review cops R-2)."""
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from claudeops.commands import web_orch


class RemoteFatal(unittest.TestCase):
    def _wait(self, status):
        calls = []

        def fake_get(path, host, q, **kw):
            calls.append(path)
            return {"ok": False}, status
        prov = SimpleNamespace(busy_status_pattern=lambda: "")
        with mock.patch.object(web_orch.web_hosts, "proxy_get", fake_get), mock.patch.object(web_orch.time, "sleep", lambda s: None):
            r = web_orch._wait_for_reply_remote("h", "n", prov, {"user": "", "assistant": ""}, timeout=60.0, poll=0.0, stable_polls=2, require_marker=None, cancel=threading.Event(), push_check=None)
        return r, len(calls)

    def test_fatal_gives_up_on_first_poll(self):
        for st in (401, 403, 404):
            r, n = self._wait(st)
            self.assertIsNone(r)
            self.assertEqual(n, 1, st)

    def test_transient_retries_until_threshold(self):
        r, n = self._wait(0)
        self.assertIsNone(r)
        self.assertEqual(n, web_orch.REMOTE_FETCH_FAILURES_BEFORE_GIVEUP)


if __name__ == "__main__":
    unittest.main()

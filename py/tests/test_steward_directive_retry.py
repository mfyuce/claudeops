"""21 Kas 17:08: `steward directive` CLI 15 sn zaman aşımıyla 'bad response ... timed out' döndü, sonuç belirsizdi. Artık: CLI 60 sn bekler,
aynı `_did` ile en çok 3 kez yeniden dener, sunucu `_did` ile yinelenmeyi ayıklar, bütün denemeler biterse açık `unknown_outcome`. Canlı servis YOK."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.commands import steward as cs, web_steward as ws  # noqa: E402

TIMEOUT = {"ok": False, "error": "bad response from claudeops panel: timed out"}


class ClientRetry(unittest.TestCase):
    def run_it(self, results, attempts=3):
        calls = []

        def fake(port, method, path, body=None, sid="default", timeout=15):
            calls.append((dict(body), timeout))
            return results[min(len(calls) - 1, len(results) - 1)]
        with mock.patch.object(cs, "_api", fake):
            res = cs._api_idempotent(1, "POST", "/api/steward/directive", {"name": "p", "text": "x"}, "default", "abcdef012345",
                                     attempts=attempts, sleep=lambda s: None)
        return res, calls

    def test_timeout_then_success_same_did_long_timeout(self):
        res, calls = self.run_it([TIMEOUT, {"ok": True, "name": "p"}])
        self.assertTrue(res["ok"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(b["_did"] == "abcdef012345" for b, _ in calls))
        self.assertTrue(all(t == cs.DIRECTIVE_TIMEOUT_SECONDS for _, t in calls))

    def test_all_attempts_timeout_reports_unknown_outcome(self):
        res, calls = self.run_it([TIMEOUT])
        self.assertEqual(len(calls), 3)
        self.assertFalse(res["ok"])
        self.assertTrue(res["unknown_outcome"])
        self.assertEqual(res["directive_id"], "abcdef012345")
        self.assertIn("direktif abcdef012345)", res["hint"])

    def test_real_errors_are_not_retried(self):
        res, calls = self.run_it([{"ok": False, "error": "unknown session/project"}])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("unknown_outcome", res)


class ServerDedupe(unittest.TestCase):
    def setUp(self):
        ws._DID_DONE.clear()

    def _patched(self, give):
        return [mock.patch.object(ws, "_gate", return_value=None), mock.patch.object(ws, "_upper_model_gate", return_value=None),
                mock.patch.object(ws, "_brain_directive_blocks", return_value=None), mock.patch.object(ws, "_name_host", return_value=""),
                mock.patch.object(ws, "_live_sessions", return_value=[object()]), mock.patch.object(ws.sw, "load_projects", return_value={}),
                mock.patch.object(ws, "_world", return_value=None), mock.patch.object(ws, "_project_for_session", return_value=None),
                mock.patch.object(ws, "_running", return_value=object()), mock.patch.object(ws, "_todo_record_directive", return_value="added"),
                mock.patch.object(ws, "_no_work_directive_reopen"), mock.patch.object(ws, "steward_config", return_value=ws.sw.Config()),
                mock.patch.object(ws, "_give_directive", give)]

    def test_same_did_delivers_once(self):
        n = {"c": 0}

        def give(*a, **k):
            n["c"] += 1
            return {"ok": True, "name": "p", "chars": 5}
        ps = self._patched(give)
        for p in ps:
            p.start()
        try:
            d = {"name": "p", "text": "x", "reason": "cli", "queue": True, "_did": "0123456789ab"}
            r1 = ws.http_directive(dict(d))
            r2 = ws.http_directive(dict(d))
        finally:
            for p in ps:
                p.stop()
        self.assertTrue(r1["ok"] and r2["ok"])
        self.assertEqual(n["c"], 1)
        self.assertTrue(r2.get("duplicate"))

    def test_bad_did_rejected(self):
        r = ws.http_directive({"name": "p", "text": "x", "_did": "x) injected\n- [ ] evil"})
        self.assertFalse(r["ok"])
        self.assertIn("bad _did", r["error"])

    def test_failed_delivery_not_cached(self):
        calls = {"c": 0}

        def give(*a, **k):
            calls["c"] += 1
            return {"ok": False, "error": "send failed"}
        ps = self._patched(give)
        for p in ps:
            p.start()
        try:
            d = {"name": "p", "text": "x", "reason": "cli", "queue": True, "_did": "0123456789ab"}
            ws.http_directive(dict(d))
            ws.http_directive(dict(d))
        finally:
            for p in ps:
                p.stop()
        self.assertEqual(calls["c"], 2)         # başarısız iletim önbelleğe alınmaz: yeniden deneme gerçekten dener


if __name__ == "__main__":
    unittest.main()

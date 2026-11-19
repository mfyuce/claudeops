"""http_review_verify: uzak projede remote_actions + taze host kapısı remote_verify'dan ÖNCE uygulanır."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class RemoteVerifyGateTest(unittest.TestCase):
    def _run(self, denied):
        cfg = mock.Mock(sid="reviewer")
        with mock.patch.object(ws, "_human_only", return_value=None), \
             mock.patch.object(ws, "_reviewer_cfg", return_value=(cfg, None)), \
             mock.patch.object(ws.web_review, "verify_candidates", return_value=[{"id": "f1"}]), \
             mock.patch.object(ws, "_ownership_index", return_value={"hosts": {"p": "remb"}, "owners": {"p": "default"}}), \
             mock.patch.object(ws, "_remote_denied", return_value=denied) as gate, \
             mock.patch.object(ws.web_review, "remote_verify", return_value={"ok": True}) as rv:
            res = ws.http_review_verify({"project": "p"}, sid="reviewer")
        return res, gate, rv

    def test_denied_host_never_reaches_remote_verify(self):
        den = {"ok": False, "code": "remote_disabled", "error": "x"}
        res, gate, rv = self._run(den)
        self.assertEqual(res["code"], "remote_disabled")
        rv.assert_not_called()
        self.assertEqual(gate.call_args.args[:3], ("p", "human", "review_verify"))

    def test_allowed_host_calls_remote_verify(self):
        res, gate, rv = self._run(None)
        self.assertTrue(res["ok"])
        rv.assert_called_once()


if __name__ == "__main__":
    unittest.main()

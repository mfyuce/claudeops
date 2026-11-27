"""Değnekçi HTTP girdisi: istemcinin `_did` kimliği sondaki satır sonunu kabul etmesin (TODO satırına yazılır). Ağ/oturum YOK."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class TrailingNewlineHttpTest(_Tmp):
    def setUp(self):
        super().setUp()
        ws._DID_DONE.clear()

    def _stubbed(self, give):
        for p in (mock.patch.object(ws, "_gate", return_value=None), mock.patch.object(ws, "_upper_model_gate", return_value=None),
                  mock.patch.object(ws, "_brain_directive_blocks", return_value=None), mock.patch.object(ws, "_name_host", return_value=""),
                  mock.patch.object(ws, "_live_sessions", return_value=[object()]), mock.patch.object(ws, "_world", return_value=None),
                  mock.patch.object(ws, "_project_for_session", return_value=None), mock.patch.object(ws, "_running", return_value=object()),
                  mock.patch.object(ws, "_todo_record_directive", return_value="added"), mock.patch.object(ws, "_no_work_directive_reopen"),
                  mock.patch.object(ws, "_give_directive", give)):
            p.start()
            self.addCleanup(p.stop)

    def test_directive_did_with_newline_rejected(self):
        give = mock.Mock(return_value={"ok": True})
        self._stubbed(give)
        r = ws.http_directive({"name": "p", "text": "x", "reason": "cli", "_did": "0123456789ab\n"})
        self.assertFalse(r["ok"])
        self.assertIn("bad _did", r["error"])
        give.assert_not_called()

    def test_queued_directive_did_with_newline_rejected(self):
        with mock.patch.object(ws, "_delivery_set") as seen, mock.patch.object(ws.threading, "Thread") as thread:
            r = ws._queue_directive({"name": "p", "text": "x", "_did": "0123456789ab\n"}, "default")
        self.assertFalse(r["ok"])
        self.assertIn("bad _did", r["error"])
        seen.assert_not_called()
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""412: `http_handover` log kaydı oturumun gerçek adını (`session`) taşır (hepsi sahte; disk/ağ YOK)."""
import contextlib
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class HandoverLogSessionTest(unittest.TestCase):
    def test_log_has_session_name(self):
        events = []
        ctx = SimpleNamespace(lock=contextlib.nullcontext())
        with mock.patch.object(ws, "steward_config", lambda sid: SimpleNamespace(lang="tr")), \
                mock.patch.object(ws, "_gate", lambda *a, **k: None), \
                mock.patch.object(ws, "_name_host", lambda n: ""), \
                mock.patch.object(ws, "_ctx", lambda sid: ctx), \
                mock.patch.object(ws, "_local_handover", lambda n, sid, lang: {"ok": True, "name": "oiso20261017"}), \
                mock.patch.object(ws, "_resolved_local_name", lambda n, sid: "oiso20261017"), \
                mock.patch.object(ws.sw, "steward_lock", lambda sid: contextlib.nullcontext()), \
                mock.patch.object(ws.sw, "load_state", lambda sid: {}), \
                mock.patch.object(ws.sw, "save_state", lambda st, sid: None), \
                mock.patch.object(ws.sw, "log_event", lambda ev, **k: events.append((ev, k))):
            res = ws.http_handover({"name": "oiso"}, "default")
        self.assertTrue(res["ok"])
        ev = [k for e, k in events if e == "handover"][0]
        self.assertEqual(ev["name"], "oiso")
        self.assertEqual(ev["session"], "oiso20261017")


if __name__ == "__main__":
    unittest.main()

"""review R-2: `_export_remote` states/only/note parametrelerini uygular (yerel `export_findings` ile aynı); sahte sürücü, ağ/disk YOK."""
import contextlib
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_review as wr  # noqa: E402


class RemoteExportParamsTest(unittest.TestCase):
    def _run(self, findings, **kw):
        seen = {}

        def export_file(fname, build, msg):
            seen["text"], _ = build("")
            return {"ok": True, "host": "h1", "path": "/x/TODO.md", "written": [k for k in findings if findings[k]["state"] in ("approved", "pending")]}
        drv = SimpleNamespace(export_file=export_file)
        saved = {}
        with mock.patch.object(wr, "ownership", lambda: {"hosts": {"p": "h1"}}), \
                mock.patch.object(wr, "_REMOTE_FN", lambda proj, host: drv), \
                mock.patch.object(wr.sw, "paths_for", lambda sid: SimpleNamespace(reviews="/r")), \
                mock.patch.object(wr.sw, "steward_lock", lambda p: contextlib.nullcontext()), \
                mock.patch.object(wr.sw, "log_event", lambda *a, **k: None), \
                mock.patch.object(wr.rv, "load_findings", lambda p: findings), \
                mock.patch.object(wr.rv, "save_findings", lambda p, d: saved.update(d)):
            r = wr._export_remote(SimpleNamespace(sid="default", lang="tr"), "p", "TODO.md", 0.0, "", **kw)
        return r, seen.get("text") or "", findings

    def test_default_only_approved(self):
        f = {"A": {"project": "p", "state": "approved", "title": "ta", "body": ""}, "B": {"project": "p", "state": "pending", "title": "tb", "body": ""}}
        r, text, f = self._run(f)
        self.assertTrue(r["ok"], r)
        self.assertEqual((f["A"]["state"], f["B"]["state"]), ("exported", "pending"))

    def test_states_only_note_applied(self):
        f = {"A": {"project": "p", "state": "approved", "title": "ta", "body": ""}, "B": {"project": "p", "state": "pending", "title": "tb", "body": ""},
             "C": {"project": "p", "state": "pending", "title": "tc", "body": ""}}
        r, text, f = self._run(f, states=("pending",), only=lambda v: v["title"] == "tb", note="NOTX")
        self.assertTrue(r["ok"], r)
        self.assertEqual((f["A"]["state"], f["B"]["state"], f["C"]["state"]), ("approved", "exported", "pending"))
        self.assertIn("NOTX", text)
        self.assertNotIn("tc", text)


if __name__ == "__main__":
    unittest.main()

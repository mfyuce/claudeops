"""_export_remote: OTOMATİKTE hassas onaylı bulgu sessizce düşmez, `skipped_sensitive` olarak raporlanır; elle yazımda yazılır (uzak sürücü sahte; ağ/disk YOK)."""
import contextlib
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_review as wr  # noqa: E402


class SkippedSensitiveTest(unittest.TestCase):
    def _run(self, findings, by="auto"):
        drv = SimpleNamespace(export_file=lambda fname, build, msg: {"ok": True, "host": "h1"})
        with mock.patch.object(wr, "ownership", lambda: {"hosts": {"p": "h1"}}), \
                mock.patch.object(wr, "_REMOTE_FN", lambda proj, host: drv), \
                mock.patch.object(wr.sw, "paths_for", lambda sid: object()), \
                mock.patch.object(wr.sw, "steward_lock", lambda p: contextlib.nullcontext()), \
                mock.patch.object(wr.sw, "log_event", lambda *a, **k: None), \
                mock.patch.object(wr.rv, "load_findings", lambda p: findings), \
                mock.patch.object(wr.rv, "save_findings", lambda p, d: None), \
                mock.patch.object(wr.sa, "is_sensitive", lambda r: "SECRET" in (r.get("title") or "")):
            return wr._export_remote(SimpleNamespace(sid="default", lang="tr"), "p", "TODO.md", 0.0, by)

    def test_only_sensitive_reports_ids_in_error(self):
        r = self._run({"F1": {"project": "p", "state": "approved", "title": "SECRET key", "body": ""}})
        self.assertFalse(r["ok"])
        self.assertEqual(r["skipped_sensitive"], ["F1"])

    def test_mixed_reports_skipped_in_success(self):
        r = self._run({"F1": {"project": "p", "state": "approved", "title": "SECRET key", "body": ""},
                       "F2": {"project": "p", "state": "approved", "title": "normal", "body": ""}})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["skipped_sensitive"], ["F1"])

    def test_manual_export_writes_sensitive(self):
        r = self._run({"F1": {"project": "p", "state": "approved", "title": "SECRET key", "body": ""}}, by="")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["skipped_sensitive"], [])


if __name__ == "__main__":
    unittest.main()

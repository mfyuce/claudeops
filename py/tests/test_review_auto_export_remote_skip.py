"""auto_export uzak (host'lu) projeleri KASITLI atlar; yerel proje yazılır (sahte export_findings; ağ/disk YOK)."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_review as wr  # noqa: E402


class AutoExportRemoteSkipTest(unittest.TestCase):
    def _run(self, hosts):
        calls = []
        findings = {"F1": {"project": "p", "state": "approved"}}
        cfg = SimpleNamespace(review_auto_export=True, sid="default", lang="tr")
        with mock.patch.object(wr, "ownership", lambda: {"hosts": hosts}), \
                mock.patch.object(wr.sw, "paths_for", lambda sid: object()), \
                mock.patch.object(wr.rv, "load_findings", lambda p: findings), \
                mock.patch.object(wr, "export_findings",
                                  lambda c, proj, fname, t, **k: calls.append((proj, fname)) or {"ok": True, "written": 1}):
            wr.auto_export(cfg, now=0.0)
        return calls

    def test_remote_project_is_skipped(self):
        self.assertEqual(self._run({"p": "h1"}), [])

    def test_local_project_is_exported(self):
        self.assertEqual(self._run({}), [("p", "TODO.md")])


if __name__ == "__main__":
    unittest.main()

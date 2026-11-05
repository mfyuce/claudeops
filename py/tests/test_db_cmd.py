import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from claudeops import store as S
from claudeops.commands import db_cmd


class DbCmdTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.st = S.Store(os.path.join(self.d, "a.db"))
        self.st.set_doc("hosts", {"x": 1})
        self.st.replace_tsv("roster.tsv", "cops\t/a\n#kapali\t/b\n")
        self.st.append_log("diag", {"e": 1})

    def test_export_import_roundtrip(self):
        data = self.st.export_all()
        self.assertEqual(data["docs"]["hosts"], {"x": 1})
        self.assertEqual(data["tsv"]["roster.tsv"], "cops\t/a\n#kapali\t/b\n")
        other = S.Store(os.path.join(self.d, "b.db"))
        n = other.import_all(json.loads(json.dumps(data)))
        self.assertEqual((n["docs"], n["tsv"], n["logs"]), (1, 1, 1))
        self.assertEqual(other.get_doc("hosts"), {"x": 1})
        self.assertEqual(other.tsv_text("roster.tsv"), "cops\t/a\n#kapali\t/b\n")
        n2 = other.import_all(data)                  # tekrar: günlük çift yazılmaz
        self.assertEqual((n2["logs"], n2["logs_skipped"]), (0, 1))
        self.assertEqual(len(other.read_log("diag")), 1)

    def test_bad_format_refused(self):
        with self.assertRaises(S.StoreError):
            self.st.import_all({"format": 9})

    def test_cli_export_dry_and_apply(self):
        out = os.path.join(self.d, "e.json")
        with mock.patch.object(db_cmd, "_store_obj", lambda: self.st), mock.patch("builtins.print"):
            self.assertEqual(db_cmd.run(SimpleNamespace(dcmd="export", out=out)), 0)
            self.assertEqual(oct(os.stat(out).st_mode & 0o777), "0o600")
            self.assertEqual(db_cmd.run(SimpleNamespace(dcmd="import", file=out, apply=False)), 0)
            with mock.patch.object(db_cmd, "CLAUDEOPS_DIR", self.d):
                self.assertEqual(db_cmd.run(SimpleNamespace(dcmd="import", file=out, apply=True)), 0)
            self.assertTrue(any(f.startswith("claudeops.db.before-import-") for f in os.listdir(os.path.join(self.d, "backups"))))


if __name__ == "__main__":
    unittest.main()

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


class DriftMaterializeTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.base = os.path.join(self.d, "cd")
        os.makedirs(os.path.join(self.base, "steward"))
        self.st = S.Store(os.path.join(self.d, "a.db"))
        self.st.set_doc("hosts", {"x": 1})
        self.st.set_doc("steward/ideas", [1, 2])

    def _w(self, name, obj):
        with open(os.path.join(self.base, name + ".json"), "w") as f:
            json.dump(obj, f)

    def test_drift_states(self):
        self._w("hosts", {"x": 1})
        self._w("steward/ideas", [1])
        self.assertEqual(dict(db_cmd.drift(self.st, base=self.base)), {"hosts": "eşit", "steward/ideas": "fark"})
        os.remove(os.path.join(self.base, "hosts.json"))
        self.assertEqual(dict(db_cmd.drift(self.st, ["hosts"], base=self.base)), {"hosts": "dosya_yok"})
        open(os.path.join(self.base, "hosts.json"), "w").write("{bozuk")
        self.assertEqual(dict(db_cmd.drift(self.st, ["hosts"], base=self.base)), {"hosts": "okunamadi"})

    def test_materialize_dry_then_apply_private_atomic(self):
        r = db_cmd.materialize(self.st, [], False, base=self.base)
        self.assertEqual({a for _, _, a in r}, {"yazılacak"})
        self.assertFalse(os.path.exists(os.path.join(self.base, "hosts.json")))     # kuru: dosya yazılmadı
        r = db_cmd.materialize(self.st, [], True, base=self.base)
        self.assertEqual({a for _, _, a in r}, {"yazıldı"})
        p = os.path.join(self.base, "steward/ideas.json")
        self.assertEqual(json.load(open(p)), [1, 2])
        self.assertEqual(oct(os.stat(p).st_mode & 0o777), "0o600")
        self.assertEqual({a for _, _, a in db_cmd.materialize(self.st, [], True, base=self.base)}, {"eşit"})

    def test_path_escape_and_unknown_rejected(self):
        for bad in ("../x", "/etc/passwd", "a/../../b", ""):
            with self.assertRaises(ValueError):
                db_cmd.doc_path(bad, self.base)
        self.assertEqual(db_cmd.materialize(self.st, ["yok"], True, base=self.base)[0][2], "yok")
        self.assertFalse(os.path.exists(os.path.join(self.base, "yok.json")))


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

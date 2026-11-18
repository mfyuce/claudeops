"""`ucli_approval.py`: kayıt defteri, suspended ayrıştırma, bekleyen listesi, cevap doğrulaması. Gerçek süreç/ağ yok."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claudeops import ucli_approval as ua  # noqa: E402


class ApprovalTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        p = mock.patch.object(ua, "ROOT", os.path.join(self.root, "ucli_approval"))
        p.start()
        self.addCleanup(p.stop)
        self.d = ua.register("run1", "/w", "s1", ["--root", "/w", "--allow-edit"], owner="alice")

    def put_pending(self, aid="a1", exp=None, run="run1"):
        exp = time.time() + 100 if exp is None else exp
        p = os.path.join(ua.dir_for(run), "pending", aid + ".json")
        with open(p, "w") as f:
            json.dump({"id": aid, "kind": "edit", "tool": "write_file", "summary": "x.txt", "created_at": 1, "expires_at": exp,
                       "status": "pending"}, f)

    def test_register_dirs_private_and_state(self):
        self.assertEqual(os.stat(self.d).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(os.path.join(self.d, "answers")).st_mode & 0o777, 0o700)
        self.assertEqual(ua.get("run1")["argv_resume"], ["--root", "/w", "--allow-edit"])
        self.assertTrue(ua.set_state("run1", "suspended"))
        self.assertEqual(ua.get("run1")["state"], "suspended")
        self.assertFalse(ua.set_state("nope", "done"))
        with self.assertRaises(ValueError):
            ua.set_state("run1", "weird")

    def test_bad_run_key(self):
        for k in ("", "../x", "A", "a/b"):
            with self.assertRaises(ValueError):
                ua.dir_for(k)

    def test_parse_suspended(self):
        out = 'noise\n{"suspended":{"id":"ab-1","state":"/s","resume":"r"}}\n'
        self.assertEqual(ua.parse_suspended(out), {"id": "ab-1"})
        self.assertIsNone(ua.parse_suspended('{"ok":true}'))
        self.assertIsNone(ua.parse_suspended('{"suspended":{"id":"../x"}}'))
        self.assertIsNone(ua.parse_suspended(""))

    def test_pending_lists_and_skips_bad_and_never_reads_suspended(self):
        self.put_pending("a1")
        self.put_pending("old", exp=1)
        with open(os.path.join(self.d, "pending", "bad.json"), "w") as f:
            f.write("{")
        with open(os.path.join(self.d, "suspended", "a1.json"), "w") as f:
            f.write('{"transcript":"SECRET"}')
        got = {p["id"]: p for p in ua.pending("run1")}
        self.assertEqual(set(got), {"a1", "old"})
        self.assertFalse(got["a1"]["expired"])
        self.assertTrue(got["old"]["expired"])
        self.assertNotIn("SECRET", json.dumps(got))

    def test_answer_ok_and_modes(self):
        self.put_pending("a1")
        ok, err = ua.answer("run1", "a1", "approve", note="tamam")
        self.assertTrue(ok, err)
        p = os.path.join(self.d, "answers", "a1.json")
        self.assertEqual(json.load(open(p)), {"id": "a1", "decision": "approve", "note": "tamam"})
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)
        ok, _ = ua.answer("run1", "a1", "edit", edited_arguments={"path": "y"})
        self.assertTrue(ok)
        self.assertEqual(json.load(open(p))["edited_arguments"], {"path": "y"})

    def test_answer_rejections(self):
        self.put_pending("a1")
        self.put_pending("old", exp=1)
        cases = [("a1", "maybe", None), ("a1", "edit", None), ("a1", "approve", {"x": 1}), ("zzz", "approve", None),
                 ("old", "approve", None), ("../a", "approve", None), ("a1", "edit", ["x"]),
                 ("a1", "edit", {"k": "v" * 70000})]
        for aid, dec, ea in cases:
            ok, err = ua.answer("run1", aid, dec, edited_arguments=ea)
            self.assertFalse(ok, (aid, dec))
            self.assertTrue(err)
        ok, _ = ua.answer("run1", "a1", "approve", note="n" * 5000)
        self.assertFalse(ok)
        self.assertEqual(os.listdir(os.path.join(self.d, "answers")), [])


if __name__ == "__main__":
    unittest.main()

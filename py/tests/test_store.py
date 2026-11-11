import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import json, os, sqlite3, stat, subprocess, sys, tempfile, threading, unittest

from claudeops import store as S


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cops-store-")
        self.p = os.path.join(self.d, "t.db")
        self.s = S.Store(self.p)

    def tearDown(self):
        self.s.close()

    def test_file_mode_0600(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.p).st_mode), 0o600)

    def test_schema_version_and_idempotent_reopen(self):
        self.assertEqual(self.s.schema_version(), len(S.MIGRATIONS))
        self.s.set_doc("a", {"x": 1})
        s2 = S.Store(self.p)
        self.assertEqual(s2.get_doc("a"), {"x": 1})
        s2.close()

    def test_newer_db_refused(self):
        c = sqlite3.connect(self.p); c.execute(f"PRAGMA user_version={len(S.MIGRATIONS) + 5}"); c.close()
        with self.assertRaises(S.StoreError):
            S.Store(self.p)

    def test_doc_roundtrip_default_version_delete(self):
        self.assertEqual(self.s.get_doc("nope", {"d": 1}), {"d": 1})
        self.assertEqual(self.s.set_doc("k", [1, "ç", {"a": None}]), 1)
        self.assertEqual(self.s.set_doc("k", [2]), 2)
        self.assertEqual(self.s.get_doc("k"), [2])
        self.assertEqual(self.s.doc_version("k"), 2)
        self.assertTrue(self.s.delete_doc("k")); self.assertFalse(self.s.delete_doc("k"))
        self.assertEqual(self.s.doc_version("k"), 0)

    def test_update_none_keeps_old_and_exception_rolls_back(self):
        self.s.set_doc("k", {"n": 1})
        self.assertEqual(self.s.update_doc("k", lambda o: None), {"n": 1})
        self.assertEqual(self.s.doc_version("k"), 1)
        with self.assertRaises(ValueError):
            self.s.update_doc("k", lambda o: (_ for _ in ()).throw(ValueError("x")))
        self.assertEqual(self.s.get_doc("k"), {"n": 1})

    def test_list_docs_prefix_escapes_like(self):
        for n in ("a/1", "a/2", "b_1", "bX1"):
            self.s.set_doc(n, 0)
        self.assertEqual(self.s.list_docs("a/"), ["a/1", "a/2"])
        self.assertEqual(self.s.list_docs("b_"), ["b_1"])   # '_' joker DEĞİL

    def test_threads_update_doc_no_lost_updates(self):
        self.s.set_doc("c", {"n": 0})
        def work():
            for _ in range(25):
                self.s.update_doc("c", lambda o: {"n": o["n"] + 1})
        ts = [threading.Thread(target=work) for _ in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(self.s.get_doc("c"), {"n": 200})

    def test_processes_update_doc_no_lost_updates(self):
        self.s.set_doc("c", {"n": 0})
        code = ("import sys; sys.path.insert(0, %r)\nfrom claudeops import store as S\ns = S.Store(%r)\n"
                "for _ in range(40): s.update_doc('c', lambda o: {'n': o['n'] + 1})\n") % (os.path.dirname(os.path.dirname(S.__file__)), self.p)
        ps = [subprocess.Popen([sys.executable, "-c", code]) for _ in range(4)]
        self.assertTrue(all(p.wait(timeout=60) == 0 for p in ps))
        self.assertEqual(self.s.get_doc("c"), {"n": 160})

    def test_log_append_read_tail_trim(self):
        ids = [self.s.append_log("diag", {"i": i}) for i in range(10)]
        self.s.append_log("other", {"z": 1})
        self.assertEqual([r[2]["i"] for r in self.s.read_log("diag", limit=3)], [0, 1, 2])
        self.assertEqual([r[2]["i"] for r in self.s.read_log("diag", after_id=ids[6])], [7, 8, 9])
        self.assertEqual([r[2]["i"] for r in self.s.tail_log("diag", 2)], [8, 9])
        self.assertEqual(self.s.trim_log("diag", 4), 6)
        self.assertEqual([r[2]["i"] for r in self.s.tail_log("diag", 99)], [6, 7, 8, 9])
        self.assertEqual(len(self.s.tail_log("other")), 1)
        self.assertEqual(self.s.trim_log("diag", 100), 0)

    def test_backup_leaves_no_tmp_and_unique_names(self):
        import glob
        dest = os.path.join(self.d, "bk2.db")
        self.s.backup(dest); self.s.backup(dest)                    # üst üste: sabit .tmp çakışması/sızıntısı yok
        self.assertEqual(glob.glob(dest + ".*.tmp") + glob.glob(dest + ".tmp"), [])
        self.assertEqual(oct(os.stat(dest).st_mode & 0o777), "0o600")

    def test_backup_failure_cleans_tmp(self):
        import glob
        from unittest import mock
        dest = os.path.join(self.d, "bk3.db")
        with mock.patch("os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.s.backup(dest)
        self.assertEqual(glob.glob(os.path.join(self.d, "bk3.db.*.tmp")), [])
        self.assertFalse(os.path.exists(dest))

    def test_backup_consistent_and_private(self):
        self.s.set_doc("a", {"v": 1}); self.s.append_log("l", 1)
        dest = os.path.join(self.d, "bk.db"); self.s.backup(dest)
        self.assertEqual(stat.S_IMODE(os.stat(dest).st_mode), 0o600)
        b = S.Store(dest); self.assertEqual(b.get_doc("a"), {"v": 1}); self.assertEqual(len(b.tail_log("l")), 1); b.close()
        self.assertFalse(os.path.exists(dest + ".tmp"))

    def test_export_docs(self):
        self.s.set_doc("x", 1); self.s.set_doc("y", {"a": 2})
        self.assertEqual(self.s.export_docs(), {"x": 1, "y": {"a": 2}})


if __name__ == "__main__":
    unittest.main()

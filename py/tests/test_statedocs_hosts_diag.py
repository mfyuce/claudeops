import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import json, tempfile, unittest
from unittest import mock
from claudeops import hosts as H, diaglog, statedocs as sd, store as S


class HostsDiagDual(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cops-hd-")
        self.st = S.Store(os.path.join(self.d, "t.db"))
        self.ps = [mock.patch.object(S, "default_store", lambda: self.st), mock.patch("claudeops.paths.CLAUDEOPS_DIR", self.d),
                   mock.patch.object(H, "HOSTS_JSON", os.path.join(self.d, "hosts.json")),
                   mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "dual", "CLAUDEOPS_DIAG_LOG": os.path.join(self.d, "diag.log")})]
        [p.start() for p in self.ps]

    def tearDown(self):
        [p.stop() for p in self.ps]; self.st.close()

    def test_hosts_dual_roundtrip_and_perm(self):
        H.save_host("ulak", "http://x:1", "tok")
        self.assertEqual([h["name"] for h in H.load_hosts()], ["ulak"])
        self.assertEqual(self.st.get_doc("hosts")[0]["token"], "tok")
        self.assertEqual(oct(os.stat(H.HOSTS_JSON).st_mode & 0o777), "0o600")

    def test_hosts_hand_edit_wins_in_dual(self):
        H.save_host("a", "http://a:1", "t")
        json.dump([{"name": "z", "base_url": "http://z", "token": "q"}], open(H.HOSTS_JSON, "w"))
        self.assertEqual([h["name"] for h in H.load_hosts()], ["z"])

    def test_hosts_db_mode_without_file(self):
        with mock.patch.dict(os.environ, {"CLAUDEOPS_STORE_BACKEND": "db"}):
            H.save_host("a", "http://a:1", "t"); self.assertFalse(os.path.exists(H.HOSTS_JSON))
            H.save_host("b", "http://b:1", "t2")
            self.assertEqual(sorted(h["name"] for h in H.load_hosts()), ["a", "b"])

    def test_diag_log_mirrors(self):
        diaglog.diag_log("ev1", k=1)
        self.assertEqual(self.st.tail_log("diag")[0][2]["event"], "ev1")
        self.assertIn("ev1", open(os.path.join(self.d, "diag.log")).read())


if __name__ == "__main__":
    unittest.main()

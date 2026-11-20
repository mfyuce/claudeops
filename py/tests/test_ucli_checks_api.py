"""run_checks C2: kayıt yazımı (0600), mod dosyası (daraltma/genişletme/tavan), denetim kaydı, authz eşlemesi."""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import authz  # noqa: E402
from claudeops import ucli_checks as uck  # noqa: E402

GOOD = {"check": [{"name": "unittest", "argv": ["python3", "-m", "unittest"]}, {"name": "tsc", "argv": ["npx", "tsc"]}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        for k, v in (("ROOT", os.path.join(self.td, "ucli_checks")), ("AUDIT", os.path.join(self.td, "ucli_checks", "audit.jsonl"))):
            p = mock.patch.object(uck, k, v)
            p.start()
            self.addCleanup(p.stop)


class Registry(Base):
    def test_save_load_0600_and_dir_0700(self):
        self.assertEqual(uck.save_registry(GOOD), (True, ""))
        path = uck.registry_path()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(uck.ROOT).st_mode), 0o700)
        self.assertEqual(uck.load_registry()[0], GOOD)

    def test_bad_shape_not_written(self):
        ok, _ = uck.save_registry({"check": [{"name": "Bad Name", "argv": ["x"]}]})
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(uck.registry_path()))

    def test_symlink_target_refused(self):
        os.makedirs(uck.ROOT, mode=0o700)
        os.symlink(os.path.join(self.td, "victim"), uck.registry_path() + ".tmp%d" % os.getpid())
        with self.assertRaises(OSError):
            uck.save_registry(GOOD)
        self.assertFalse(os.path.exists(os.path.join(self.td, "victim")))

    def test_delete(self):
        uck.save_registry(GOOD)
        self.assertEqual(uck.delete_check("tsc"), (True, ""))
        self.assertEqual([c["name"] for c in uck.load_registry()[0]["check"]], ["unittest"])
        self.assertFalse(uck.delete_check("yok")[0])


class Mode(Base):
    def sd(self):
        return os.path.join(self.td, "state")

    def test_narrow_without_confirm_and_seq_increments(self):
        c, r = uck.set_mode(self.sd(), "s1", "restricted", "full", confirm=True, user="u")
        self.assertEqual((c, r["seq"]), (200, 1))
        c, r = uck.set_mode(self.sd(), "s1", "off", "full", user="u", ip="1.2.3.4")
        self.assertEqual((c, r["seq"]), (200, 2))
        d = json.load(open(uck.mode_file(self.sd(), "s1")))
        self.assertEqual((d["mode"], d["seq"], d["set_by"]), ("off", 2, "u"))
        self.assertEqual(stat.S_IMODE(os.stat(uck.mode_file(self.sd(), "s1")).st_mode), 0o600)

    def test_widen_needs_confirm(self):
        c, r = uck.set_mode(self.sd(), "s1", "restricted", "full")
        self.assertEqual(c, 400)
        self.assertTrue(r["need_confirm"])
        self.assertFalse(os.path.exists(uck.mode_file(self.sd(), "s1")))

    def test_above_cap_409(self):
        c, _ = uck.set_mode(self.sd(), "s1", "full", "restricted", confirm=True)
        self.assertEqual(c, 409)

    def test_audit_written(self):
        uck.set_mode(self.sd(), "s1", "restricted", "full", confirm=True, user="alice", ip="9.9.9.9")
        rec = json.loads(open(uck.AUDIT).read().splitlines()[-1])
        self.assertEqual((rec["user"], rec["session"], rec["from"], rec["to"], rec["max"], rec["ip"]),
                         ("alice", "s1", "off", "restricted", "full", "9.9.9.9"))
        self.assertEqual(stat.S_IMODE(os.stat(uck.AUDIT).st_mode), 0o600)

    def test_bad_inputs(self):
        self.assertEqual(uck.set_mode(self.sd(), "s1", "bogus", "full")[0], 400)
        self.assertEqual(uck.set_mode(self.sd(), "../x", "off", "full")[0], 400)


    def test_get_mode_reads_file_default_off(self):
        self.assertEqual(uck.get_mode(self.sd(), "s1"), {"mode": "off", "seq": 0})
        uck.set_mode(self.sd(), "s1", "restricted", "full", confirm=True)
        self.assertEqual(uck.get_mode(self.sd(), "s1"), {"mode": "restricted", "seq": 1})
        self.assertEqual(uck.get_mode(self.sd(), "../x"), {"mode": "off", "seq": 0})


class Authz(unittest.TestCase):
    def test_actions(self):
        self.assertEqual(authz.action_for("POST", "/api/ucli/checks"), "admin.config")
        self.assertEqual(authz.action_for("POST", "/api/ucli/checks-mode"), "session.control")
        self.assertEqual(authz.action_for("GET", "/api/ucli/checks"), "admin.config")


if __name__ == "__main__":
    unittest.main()

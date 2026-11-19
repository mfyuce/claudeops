"""run_checks C1: ucli_checks seçenek doğrulaması, kayıt ön denetimi, _apply_cli_opts kapıları (sahte ikili: gerçek ucli yok)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_checks as uck  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402
from claudeops.ucli_session_opts import validate_opts  # noqa: E402

GOOD = {"check": [{"name": "unittest", "argv": ["python3", "-m", "unittest"]}]}


class Validate(unittest.TestCase):
    def test_off_by_default_and_dropped(self):
        for v in (None, "", False, {}):
            out, err = validate_opts({"ucli_checks": v})
            self.assertEqual((out.get("ucli_checks"), err), (None, ""))

    def test_restricted_ok_max_defaults_to_mode(self):
        out, err = validate_opts({"ucli_checks": {"mode": "restricted"}})
        self.assertEqual(err, "")
        self.assertEqual(out["ucli_checks"], {"mode": "restricted", "max": "restricted", "accept_risk": False})

    def test_errors(self):
        for bad in ("on", {"mode": "x"}, {"mode": "restricted", "max": "bogus"}, {"mode": "full", "max": "restricted", "accept_risk": True}):
            self.assertNotEqual(validate_opts({"ucli_checks": bad})[1], "", bad)

    def test_full_needs_accept_risk(self):
        self.assertNotEqual(validate_opts({"ucli_checks": {"mode": "full"}})[1], "")
        self.assertNotEqual(validate_opts({"ucli_checks": {"mode": "restricted", "max": "full"}})[1], "")
        out, err = validate_opts({"ucli_checks": {"mode": "full", "accept_risk": True}})
        self.assertEqual((err, out["ucli_checks"]["max"]), ("", "full"))


class Registry(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        p = mock.patch.object(uck, "ROOT", tmp)
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tmp

    def write(self, data, mode=0o600):
        path = os.path.join(self.tmp, "owner.json")
        with open(path, "w") as f:
            json.dump(data, f)
        os.chmod(path, mode)

    def test_missing_loose_mode_and_shape(self):
        self.assertIn("kaydı yok", uck.load_registry()[1])
        self.write(GOOD, 0o644)
        self.assertIn("0600", uck.load_registry()[1])
        self.write({"check": [{"name": "A!", "argv": ["x"]}]})
        self.assertNotEqual(uck.load_registry()[1], "")
        self.write({"check": [{"name": "a", "argv": ["x"]}, {"name": "a", "argv": ["y"]}]})
        self.assertIn("yinelendi", uck.load_registry()[1])
        self.write(GOOD)
        self.assertEqual(uck.load_registry()[1], "")

    def test_symlink_rejected(self):
        real = os.path.join(self.tmp, "real.json")
        open(real, "w").write(json.dumps(GOOD))
        os.chmod(real, 0o600)
        os.symlink(real, os.path.join(self.tmp, "owner.json"))
        self.assertIn("düz dosya", uck.load_registry()[1])


class Apply(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        for p in (mock.patch.object(uck, "ROOT", tmp), mock.patch.object(up, "diag_log", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        path = os.path.join(tmp, "owner.json")
        open(path, "w").write(json.dumps(GOOD))
        os.chmod(path, 0o600)
        self.path = path

    def apply(self, uc, supports=lambda b, f: True, argv=("ucli", "chat", "--state-dir", "/s")):
        with mock.patch.object(up, "binary_supports_flag", supports):
            return up._apply_cli_opts(list(argv), {"ucli_checks": uc}, "sess", "/x", "")[0]

    def test_flags_added(self):
        argv = self.apply({"mode": "restricted", "max": "restricted", "accept_risk": False})
        i = argv.index("--allow-checks")
        self.assertEqual(argv[i + 1], "restricted")
        self.assertEqual(argv[argv.index("--checks-file") + 1], self.path)
        self.assertNotIn("--checks-accept-risk", argv)

    def test_full_adds_accept_risk(self):
        argv = self.apply({"mode": "full", "max": "full", "accept_risk": True})
        self.assertIn("--checks-accept-risk", argv)

    def test_unsupported_binary_refused(self):
        with self.assertRaises(ValueError):
            self.apply({"mode": "restricted", "max": "restricted", "accept_risk": False}, supports=lambda b, f: f != "--allow-checks")

    def test_needs_state_dir_and_registry(self):
        with self.assertRaises(ValueError):
            self.apply({"mode": "restricted", "max": "restricted", "accept_risk": False}, argv=("ucli", "chat"))
        os.unlink(self.path)
        with self.assertRaises(ValueError):
            self.apply({"mode": "restricted", "max": "restricted", "accept_risk": False})


if __name__ == "__main__":
    unittest.main()

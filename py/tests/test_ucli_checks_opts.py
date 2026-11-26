"""run_checks C1: ucli_checks seçenek doğrulaması, kayıt ön denetimi, _apply_cli_opts kapıları (sahte ikili: gerçek ucli yok)."""
import json
import os
import sys
import tempfile
import threading
import time
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


class ReadModifyWrite(unittest.TestCase):
    """Eşzamanlı oku-değiştir-yaz güncellemeyi kaybetmemeli (yazım yapay olarak yavaşlatılır: kilitsiz kod her koşuda düşer)."""

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        real = uck.atomic_write_text

        def slow(*a, **k):
            time.sleep(0.05)
            real(*a, **k)
        for target, value in (("ROOT", tmp), ("AUDIT", os.path.join(tmp, "audit.jsonl")), ("atomic_write_text", slow)):
            p = mock.patch.object(uck, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.tmp = tmp

    def run_all(self, calls):
        out = [None] * len(calls)

        def go(i):
            out[i] = calls[i]()
        ts = [threading.Thread(target=go, args=(i,)) for i in range(len(calls))]
        for t in ts:
            t.start()
        for t in ts:
            t.join(20)
        return out

    def test_set_mode_seq_counts_every_write(self):
        res = self.run_all([lambda: uck.set_mode(self.tmp, "s", "off", "full") for _ in range(4)])
        self.assertEqual(sorted(r[1]["seq"] for r in res), [1, 2, 3, 4])

    def test_two_deletes_both_stick(self):
        three = [{"name": n, "argv": ["x"]} for n in ("a", "b", "c")]
        self.assertEqual(uck.save_registry({"check": three}), (True, ""))
        res = self.run_all([lambda: uck.delete_check("a"), lambda: uck.delete_check("b")])
        self.assertEqual(res, [(True, ""), (True, "")])
        self.assertEqual([c["name"] for c in uck.load_registry()[0]["check"]], ["c"])


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

    def test_full_refused_when_binary_only_knows_restricted(self):
        """C4 bulgusu: gerçek ucli (U5'ten önce) `--allow-checks full`u 'invalid value' ile reddediyor; açılışta net hata."""
        help_txt = "--allow-checks <X>\n [possible values: restricted]\n--checks-max <Y>\n [possible values: restricted]\n"
        with mock.patch("claudeops.ucli_client.chat_help_text", return_value=help_txt):
            with self.assertRaises(ValueError) as cm:
                self.apply({"mode": "full", "max": "full", "accept_risk": True})
            self.assertIn("full", str(cm.exception))
            argv = self.apply({"mode": "restricted", "max": "restricted", "accept_risk": False})   # restricted geçer
        self.assertIn("--allow-checks", argv)

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

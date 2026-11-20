"""run_checks C4: gerçek ucli ikilisiyle kayıt doğrulaması (ikili yoksa atlanır). Şablonların hepsi `ucli checks validate`ten geçmeli."""
import json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import ucli_checks as uck  # noqa: E402
from claudeops.ucli_client import resolve_binary  # noqa: E402

try:
    BIN = resolve_binary()
except Exception:
    BIN = ""
HAVE = bool(BIN) and os.path.exists(BIN) and uck.binary_supports_checks(BIN)


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        for k, v in (("ROOT", os.path.join(self.td, "ucli_checks")), ("AUDIT", os.path.join(self.td, "ucli_checks", "audit.jsonl"))):
            p = mock.patch.object(uck, k, v); p.start(); self.addCleanup(p.stop)


@unittest.skipUnless(HAVE, "gerçek ucli ikilisi (checks alt komutu) yok")
class RealBinary(Base):
    def test_every_template_validates(self):
        for name, tpl in uck.TEMPLATES.items():
            ok, errs = uck.ucli_validate({"version": 1, "check": [tpl]}, BIN)
            self.assertTrue(ok, f"{name}: {errs}")

    def test_save_adds_version_and_real_validation_rejects_bad(self):
        self.assertEqual(uck.save_registry({"check": [uck.TEMPLATES["git status"]]}, binary=BIN), (True, ""))
        self.assertEqual(uck.load_registry()[0]["version"], 1)
        ok, why = uck.save_registry({"check": [{"name": "x", "argv": ["git", "status"], "env": {"LD_PRELOAD": "/x"}}]}, binary=BIN)
        self.assertFalse(ok)
        self.assertIn("LD_PRELOAD", why + json.dumps(why))


class Unit(Base):
    def test_version_defaults_to_1_without_binary(self):
        self.assertEqual(uck.save_registry({"check": [uck.TEMPLATES["git log"]]}, binary=""), (True, ""))
        self.assertEqual(uck.load_registry()[0]["version"], 1)

    def test_validation_failure_blocks_write(self):
        with mock.patch.object(uck, "ucli_validate", return_value=(False, "bad env")), mock.patch.object(uck, "binary_supports_checks", return_value=True):
            ok, why = uck.save_registry({"check": [uck.TEMPLATES["git log"]]}, binary="/x/ucli")
        self.assertEqual((ok, why), (False, "bad env"))
        self.assertFalse(os.path.exists(uck.registry_path()))


if __name__ == "__main__":
    unittest.main()

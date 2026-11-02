import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.providers.ucli_provider import UcliProvider  # noqa: E402


class BrainPermission(unittest.TestCase):
    def test_default_allow_edit_is_a_valid_ucli_mode(self):
        self.assertEqual(sw.Config().brain_permission, "allow-edit")
        self.assertIn("allow-edit", UcliProvider().permission_modes())

    def test_applied_only_for_ucli(self):
        src = open(os.path.join(os.path.dirname(sw.__file__), "commands", "web_steward.py"), encoding="utf-8").read()
        self.assertIn('if cli == "ucli" and cfg.brain_permission in (provider.permission_modes() or []):', src)


if __name__ == "__main__":
    unittest.main()

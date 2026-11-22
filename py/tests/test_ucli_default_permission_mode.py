"""Panel varsayılanı: ucli oturumları allow-edit ile ön-seçili; sunucu içi yollar permission_modes()[0] (read-only) kalır."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.providers import PROVIDERS, get_provider  # noqa: E402


class DefaultPermissionMode(unittest.TestCase):
    def test_ucli_panel_default_is_allow_edit_and_listed(self):
        p = get_provider("ucli")
        self.assertEqual(p.default_permission_mode(), "allow-edit")
        self.assertIn("allow-edit", p.permission_modes())

    def test_ucli_server_internal_default_stays_read_only(self):
        # steward beyni / diag ask / stuck permission_modes()[0]'a güvenir
        self.assertEqual(get_provider("ucli").permission_modes()[0], "read-only")

    def test_other_providers_keep_auto(self):
        for name, p in PROVIDERS.items():
            if name != "ucli":
                self.assertEqual(p.default_permission_mode(), "auto", name)


if __name__ == "__main__":
    unittest.main()

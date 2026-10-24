"""agy provider: ikili yolu çözülmüş (Ayarlar override) ve kabuk için alıntılı kullanılır (stdlib unittest)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.providers import agy_provider  # noqa: E402
from claudeops.providers.agy_provider import AgyProvider  # noqa: E402


class AgyBinaryTest(unittest.TestCase):
    def test_inner_command_quotes_a_path_with_spaces(self):
        with mock.patch.object(agy_provider, "resolved_binary", lambda n: "/opt/my tools/agy"):
            cmd = AgyProvider().build_inner_command("/w", "gemini-3.8-flash-medium", "default", "medium", None, "", "s1")
        self.assertTrue(cmd.startswith("'/opt/my tools/agy' "), cmd)

    def test_model_choices_uses_the_resolved_binary(self):
        seen = []

        def run(argv, **k):
            seen.append(argv)
            return mock.Mock(stdout="Fetching\nm1\tM One\n")
        p = AgyProvider()
        p._cache_ts = 0.0
        with mock.patch.object(agy_provider, "resolved_binary", lambda n: "/opt/agy"), \
             mock.patch.object(agy_provider.subprocess, "run", run):
            self.assertIn("m1", p.model_choices())
        self.assertEqual(seen, [["/opt/agy", "models"]])


if __name__ == "__main__":
    unittest.main()

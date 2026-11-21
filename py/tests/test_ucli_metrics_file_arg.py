"""ucli `--metrics-file`: ayar açık + ikili tanıyorsa argv'ye girer; kapalı/tanımıyorsa/adsız girmez."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_metrics  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


class MetricsFileArgs(unittest.TestCase):
    def run_it(self, enabled=True, supports=True, name="s1"):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("claudeops.paths.CLAUDEOPS_DIR", d), \
                mock.patch.object(ucli_metrics, "get_config", lambda raw=None: {"enabled": enabled}), \
                mock.patch.object(up, "binary_supports_flag", lambda b, f: supports):
            return up._metrics_file_args("ucli", name), d

    def test_on_and_supported(self):
        a, d = self.run_it()
        self.assertEqual(a[0], "--metrics-file")
        self.assertEqual(a[1], os.path.join(d, "ucli_metrics", "s1.jsonl"))

    def test_off_unsupported_nameless(self):
        self.assertEqual(self.run_it(enabled=False)[0], [])
        self.assertEqual(self.run_it(supports=False)[0], [])
        self.assertEqual(self.run_it(name="")[0], [])

    def test_name_sanitised(self):
        a, _ = self.run_it(name="a/b c")
        self.assertTrue(a[1].endswith("a_b_c.jsonl"))


if __name__ == "__main__":
    unittest.main()

"""tunnel.log'a panel token'ı düşmemeli: run-tunnel.sh çıktıyı sed ile arındırır, unit UMask=0077 taşır."""
import os
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import service  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "claudeops", "data", "run-tunnel.sh")


class TunnelLogRedactionTest(unittest.TestCase):
    def test_unit_template_has_umask(self):
        self.assertIn("UMask=0077", service.TUNNEL_UNIT_TEMPLATE)

    def test_script_redirects_output_through_sed_and_runs_real_lines(self):
        src = open(SCRIPT, encoding="utf-8").read()
        lines = [ln for ln in src.splitlines() if ln.startswith("exec 3>&1") or ln.startswith("exec > >(sed")]
        self.assertEqual(len(lines), 2, lines)
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "t.log")
            body = "\n".join(lines) + "\necho 'ERR dest=https://x.trycloudflare.com/api/status?token=SECRET123&a=1'\necho 'ok line'\n"
            subprocess.run(["bash", "-c", body], stdout=open(log, "a"), stderr=subprocess.STDOUT, check=True)
            import time
            time.sleep(0.3)  # sed alt süreci son satırı yazsın
            out = open(log).read()
        self.assertNotIn("SECRET123", out)
        self.assertIn("token=REDACTED&a=1", out)
        self.assertIn("ok line", out)


if __name__ == "__main__":
    unittest.main()

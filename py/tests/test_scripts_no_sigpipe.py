"""`set -o pipefail` altında `tr ... </dev/urandom | head -c N` SIGPIPE (141) ile betiği sessizce bitirir (review uzops R-8/R-5, 17 Kas).
Betiklerde bu boru hattı ya hiç olmamalı ya da `|| true` ile korunmalı."""
import os
import re
import subprocess
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")


class NoUnguardedUrandomPipe(unittest.TestCase):
    def test_no_unguarded_tr_urandom_head(self):
        for fn in sorted(os.listdir(SCRIPTS)):
            if not fn.endswith(".sh"):
                continue
            for n, line in enumerate(open(os.path.join(SCRIPTS, fn), encoding="utf-8"), 1):
                if line.lstrip().startswith("#"):
                    continue
                if re.search(r"/dev/urandom\s*\|\s*head", line) and "|| true" not in line:
                    self.fail(f"{fn}:{n}: korumasız urandom|head: {line.strip()}")

    def test_pipeline_really_kills_under_pipefail(self):
        r = subprocess.run(["bash", "-c", 'set -euo pipefail; X="$(tr -dc a-z < /dev/urandom | head -c 10)"; echo ok'], capture_output=True)
        self.assertNotEqual(r.returncode, 0)          # sorunun gerçek olduğunun kanıtı (koruma gerekçesi)

    def test_scripts_syntax(self):
        for fn in ("bootstrap-remote-host.sh", "provision-user.sh"):
            self.assertEqual(subprocess.run(["bash", "-n", os.path.join(SCRIPTS, fn)]).returncode, 0, fn)


if __name__ == "__main__":
    unittest.main()

"""OPS-04: bash `claudeops` isim-kısaltma Python-dönemi `cops20260930_1` adını `_`'de kesiyordu ("cops20260930_" kalıyor,
boot.list'teki "cops" ile eşleşmeyip duplicate oturum açılıyordu). Ortak base_name(): sondaki rakam + _rakam öbekleri atılır."""
import os
import re
import subprocess
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "claudeops")


def base(name):
    src = open(SCRIPT, encoding="utf-8").read()
    m = re.search(r"^base_name\(\) \{.*?^\}\n", src, re.S | re.M)
    code = (m.group(0) if m else "") + f'\nbase_name {name!r}'
    r = subprocess.run(["bash", "-c", code], capture_output=True, text=True, timeout=20)
    return r.stdout.strip()


class BaseNameTest(unittest.TestCase):
    def test_cases(self):
        for given, want in [("hc58", "hc"), ("hc", "hc"), ("cops20260930_1", "cops"), ("cops20260930", "cops"),
                            ("cops_2", "cops"), ("shell_yuhem", "shell_yuhem"), ("mtsyn20261001_3", "mtsyn"), ("a1b2", "a1b")]:
            self.assertEqual(base(given), want, given)

    def test_no_raw_sed_left(self):
        src = open(SCRIPT, encoding="utf-8").read()
        self.assertEqual(src.count("sed -E 's/[0-9]+$//'"), 0)

"""GATE-TODO3 #3: py/webui/dist/index.html'in referans verdiği js/css dosyaları diskte VAR ve git'te İZLİ olmalı.
(Eksikse sunucu boş sayfa verir; izsizse başka makinede/commit'te kaybolur.)
Çalıştırma:  python3 py/tests/test_dist_consistent.py -v
"""
import os
import re
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.normpath(os.path.join(HERE, "..", "webui", "dist"))
INDEX = os.path.join(DIST, "index.html")


def _refs():
    with open(INDEX, encoding="utf-8") as f:
        html = f.read()
    refs = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    return [r.lstrip("/") for r in refs]


class DistConsistentTests(unittest.TestCase):
    def test_index_references_something(self):
        refs = _refs()
        self.assertTrue(any(r.endswith(".js") for r in refs), refs)
        self.assertTrue(any(r.endswith(".css") for r in refs), refs)

    def test_referenced_assets_exist_on_disk(self):
        for r in _refs():
            p = os.path.join(DIST, r)
            self.assertTrue(os.path.isfile(p), f"index.html {r} dosyasına referans veriyor ama diskte yok")

    def test_referenced_assets_are_tracked_in_git(self):
        if not shutil.which("git"):
            self.skipTest("git yok")
        probe = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=DIST,
                               capture_output=True, text=True)
        if probe.returncode != 0:
            self.skipTest("git deposu değil")
        for r in ["index.html"] + _refs():
            res = subprocess.run(["git", "ls-files", "--error-unmatch", r if r == "index.html" else r],
                                 cwd=DIST, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"{r} git'te izli değil: {res.stderr.strip()}")


if __name__ == "__main__":
    unittest.main()

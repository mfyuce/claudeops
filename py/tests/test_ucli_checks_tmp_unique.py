"""Review R-2/R-3 (21 Kas, ucli_checks.py:154,213): `save_registry` / `set_mode` sabit `<yol>.tmp<pid>` kullanıyordu; aynı süreçteki
eşzamanlı HTTP istekleri aynı geçici dosyayı ezer. Her yazımın geçici adı benzersiz olmalı (iş parçacığı başına)."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_checks as uck  # noqa: E402

GOOD = {"check": [{"name": "unittest", "argv": ["python3", "-m", "unittest"]}]}


class TmpUniqueTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        for k, v in (("ROOT", os.path.join(self.td, "ucli_checks")), ("AUDIT", os.path.join(self.td, "ucli_checks", "audit.jsonl"))):
            p = mock.patch.object(uck, k, v)
            p.start()
            self.addCleanup(p.stop)

    def _tmps_from_two_threads(self, fn):
        seen = []
        real = os.replace
        lock = threading.Lock()

        bar = threading.Barrier(2, timeout=10)

        def rec(src, dst, *a, **k):
            with lock:
                seen.append(os.path.basename(src))
            bar.wait()        # iki iş parçacığı da canlıyken (thread kimliği yeniden kullanılmaz) adlandırma karşılaştırılır
            return real(src, dst, *a, **k)

        with mock.patch.object(os, "replace", rec):
            ts = [threading.Thread(target=fn) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        return [s for s in seen if ".tmp" in s]

    def test_save_registry_tmp_name_unique_per_thread(self):
        tmps = self._tmps_from_two_threads(lambda: uck.save_registry(GOOD))
        self.assertEqual(len(tmps), 2, tmps)
        self.assertEqual(len(set(tmps)), 2, f"iki iş parçacığı aynı tmp adını kullandı: {tmps}")

    def test_set_mode_tmp_name_unique_per_thread(self):
        sd = os.path.join(self.td, "state")
        tmps = self._tmps_from_two_threads(lambda: uck.set_mode(sd, "s1", "restricted", "full", confirm=True))
        self.assertEqual(len(tmps), 2, tmps)
        self.assertEqual(len(set(tmps)), 2, f"iki iş parçacığı aynı tmp adını kullandı: {tmps}")

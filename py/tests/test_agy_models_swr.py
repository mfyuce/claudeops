"""agy model listesi: bayat ama dolu önbellek istek iş parçacığını BEKLETMEZ (arka planda yenilenir); soğukta bloklar."""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers import agy_provider as ap  # noqa: E402


class _Out:
    def __init__(self, text):
        self.returncode, self.stdout = 0, text


class AgyModelsSwr(unittest.TestCase):
    def test_cold_blocks_then_stale_returns_old_immediately_and_refreshes_in_background(self):
        p = ap.AgyProvider()
        gate = threading.Event()
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if len(calls) > 1:
                gate.wait(5)                     # arka plan yenilemesi yavaş
                return _Out("Fetching...\nm-new\tYeni\n")
            return _Out("Fetching...\nm-old\tEski\n")
        with mock.patch.object(ap, "_run_grouped", fake_run), mock.patch.object(ap, "resolved_binary", lambda n: n):
            self.assertEqual(p.model_choices(), ["m-old"])          # soğuk: bloklayarak çekti
            p._cache_ts = time.monotonic() - ap._MODELS_TTL - 1      # TTL doldu
            t = time.monotonic()
            self.assertEqual(p.model_choices(), ["m-old"])          # bayat: eskiyi hemen döndürür
            self.assertLess(time.monotonic() - t, 1.0)
            gate.set()
            for _ in range(50):
                if p._cache_models == ["m-new"]:
                    break
                time.sleep(0.05)
            self.assertEqual(p.model_choices(), ["m-new"])          # arka plan yeniledi
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()

"""R-B2a-4 (28 Kas gözden geçirme): `_find_running_for_action` taraması tek-uçuş. Soğuk önbellekte (ör. 17 mirror aynı anda
düşünce) eşzamanlı N çözüm N tam `/proc` taraması yapıyordu; çağrıdan SONRA başlamış bir tarama paylaşılır (tazelik
aynı), sıralı çağrılar yine ayrı tarar. Patlamada en çok iki tarama: süren tarama + o sürerken gelenlerin ortak taraması.

Çalıştırma:  python3 -m unittest discover -s py/tests -p 'test_term_scan_coalesce.py' -v
"""
import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402


class ScanCoalesceTests(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        self.gate = threading.Event()
        self.lock = threading.Lock()

        def fake_find_sessions(measure_cpu=True):
            with self.lock:
                self.calls += 1
            self.gate.wait(5)
            return [SimpleNamespace(name="a", cli="claude", pid=1), SimpleNamespace(name="b", cli="claude", pid=2)]

        p = mock.patch.object(web, "find_sessions", fake_find_sessions)
        p.start()
        self.addCleanup(p.stop)

    def test_concurrent_resolves_share_one_scan(self):
        out = {}

        def run(n):
            out[n] = web._find_running_for_action(n)

        first = threading.Thread(target=run, args=("a",))
        first.start()
        time.sleep(0.1)  # ilk tarama sürüyor
        self.gate.set()
        first.join(5)
        self.gate.clear()
        ts = [threading.Thread(target=run, args=(n,)) for n in ("a", "b", "a", "b")]
        for t in ts:
            t.start()
        time.sleep(0.2)  # dördü de kilitte ya da taramada
        self.gate.set()
        for t in ts:
            t.join(5)
        self.assertEqual(out["a"][0], "exact")
        self.assertEqual(out["b"][1][0].name, "b")
        # ilk çağrı 1 tarama; eşzamanlı dördü: biri taramaya girer, o sürerken gelenler bir SONRAKİ ortak taramayı paylaşır
        # (kendi girişlerinden önce başlamış tarama kullanılmaz): en çok 2 (eski davranış 4)
        self.assertLessEqual(self.calls - 1, 2, "eşzamanlı dört çözüm en çok iki taramayı paylaşmalı")

    def test_sequential_calls_scan_fresh(self):
        self.gate.set()
        web._find_running_for_action("a")
        web._find_running_for_action("a")
        self.assertEqual(self.calls, 2, "sıralı çağrı eski taramayı yeniden kullanmamalı")


if __name__ == "__main__":
    unittest.main()

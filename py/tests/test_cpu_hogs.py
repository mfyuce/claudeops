"""orphan_watch CPU yakan uyarısı (21 Kas): iki örnek arası ortalama > %300, kısa pencerede eski örnek korunur, pid yeniden kullanımı sayılmaz."""
import os
import sys
import unittest
from collections import namedtuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import orphan_watch as ow  # noqa: E402

CT = namedtuple("CT", "user system")
UIDS = namedtuple("UIDS", "real effective saved")
ME = UIDS(os.getuid(), os.getuid(), os.getuid())     # içerik yalnız kendi sürecimizde okunur (TBD#365)


class P:
    def __init__(self, pid, name, cpu, created=1000.0):
        self.info = {"pid": pid, "name": name, "cmdline": [name, "x"], "create_time": created, "cpu_times": CT(cpu, 0.0), "uids": ME}


class Hogs(unittest.TestCase):
    def test_hog_detected_after_window(self):
        _, tab = ow.scan_cpu_hogs({}, now=1000.0, procs=[P(10, "moss", 100.0), P(11, "calm", 100.0)])
        hogs, tab2 = ow.scan_cpu_hogs(tab, now=1720.0, procs=[P(10, "moss", 100.0 + 720 * 5.0), P(11, "calm", 110.0)])
        self.assertEqual([(h["pid"], h["pct"]) for h in hogs], [(10, 500)])
        self.assertEqual(hogs[0]["name"], "moss")
        self.assertIn("10", tab2)

    def test_short_window_keeps_old_sample_and_no_alarm(self):
        _, tab = ow.scan_cpu_hogs({}, now=1000.0, procs=[P(10, "moss", 100.0)])
        hogs, tab2 = ow.scan_cpu_hogs(tab, now=1060.0, procs=[P(10, "moss", 100.0 + 60 * 8)])
        self.assertEqual(hogs, [])
        self.assertEqual(tab2["10"][1], 1000.0)

    def test_pid_reuse_not_counted(self):
        _, tab = ow.scan_cpu_hogs({}, now=1000.0, procs=[P(10, "a", 100.0, created=900.0)])
        hogs, _ = ow.scan_cpu_hogs(tab, now=2000.0, procs=[P(10, "b", 9000.0, created=1500.0)])
        self.assertEqual(hogs, [])


if __name__ == "__main__":
    unittest.main()

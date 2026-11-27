"""ucli_metrics: sahte /proc ağacı ile RSS/CPU/io, çocuk toplama, retention, API biçimi + yetki, boşta iş yapmama, enabled=false, maliyet."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import authz  # noqa: E402
from claudeops import ucli_metrics as um  # noqa: E402


def fake_proc(root, pid, ppid, ticks=(0, 0), rss_pages=0, rb=0, wb=0, comm="ucli (x y)", io=True):
    d = os.path.join(root, str(pid))
    os.makedirs(d, exist_ok=True)
    pad = " ".join(["0"] * 9)   # pgrp session tty tpgid flags minflt cminflt majflt cmajflt
    with open(os.path.join(d, "stat"), "w") as f:
        f.write(f"{pid} ({comm}) S {ppid} {pad} {ticks[0]} {ticks[1]} 0 0 20 0 1 0 100 0 0\n")
    with open(os.path.join(d, "statm"), "w") as f:
        f.write(f"1000 {rss_pages} 0 0 0 0 0\n")
    if io:
        with open(os.path.join(d, "io"), "w") as f:
            f.write(f"rchar: 1\nwchar: 1\nread_bytes: {rb}\nwrite_bytes: {wb}\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.proc = os.path.join(self.td, "proc")
        os.makedirs(self.proc)
        self.db = os.path.join(self.td, "m.db")
        self.t = [1000.0]
        self.sessions = [("u1", 10, "")]

    def sampler(self, **kw):
        return um.Sampler(discover=lambda: list(self.sessions), proc_root=self.proc, path=self.db, now=lambda: self.t[0],
                          disk=kw.get("disk", lambda c: 123))


class Compute(Base):
    def test_rss_io_children_cpu(self):
        # ağaç: 10 -> 11 (bwrap) -> 12; 99 ilgisiz
        fake_proc(self.proc, 10, 1, (100, 0), rss_pages=100, rb=10, wb=20)
        fake_proc(self.proc, 11, 10, (0, 0), rss_pages=50, rb=1, wb=2, comm="bwrap")
        fake_proc(self.proc, 12, 11, (0, 0), rss_pages=25, io=False)          # io okunamaz -> 0
        fake_proc(self.proc, 99, 1, (500, 500), rss_pages=999)
        self.sessions = [("u1", 10, self.td)]
        s = self.sampler()
        with mock.patch.object(um, "_CLK", 100):
            self.assertEqual(s.sample_once(), 1)
            self.t[0] += 10
            fake_proc(self.proc, 10, 1, (150, 50), rss_pages=100, rb=10, wb=20)   # +100 tik / 100 / 10 sn = %10
            s.sample_once()
        r = um.query("u1", path=self.db)["samples"]
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0]["procs"], 3)
        self.assertEqual(r[0]["rss_kib"], 175 * um._PAGE // 1024)
        self.assertEqual((r[0]["io_r"], r[0]["io_w"]), (11, 22))
        self.assertEqual(r[0]["cpu_pct"], 0.0)
        self.assertAlmostEqual(r[1]["cpu_pct"], 10.0, places=1)
        self.assertEqual(r[0]["disk_b"], 123)
        self.assertIsNone(r[1]["disk_b"])          # 5 dk dolmadı

    def test_stat_comm_with_parens(self):
        self.assertEqual(um.parse_stat("5 (a) b c) S 7 0 0 0 0 0 0 0 0 0 3 4 0"), (7, 7))

    def test_disk_limits(self):
        d = os.path.join(self.td, "w")
        os.makedirs(d)
        for i in range(5):
            with open(os.path.join(d, f"f{i}"), "w") as f:
                f.write("x" * 10)
        self.assertEqual(um.disk_usage(d), 50)
        self.assertIsNone(um.disk_usage(d, max_files=3))
        ticks = iter(range(0, 100))
        self.assertIsNone(um.disk_usage(d, timeout=2, clock=lambda: next(ticks)))

    def test_disk_every_5min(self):
        fake_proc(self.proc, 10, 1)
        calls = []
        s = self.sampler(disk=lambda c: calls.append(c) or 1)
        self.sessions = [("u1", 10, self.td)]
        for dt in (0, 15, 100, 301):
            self.t[0] = 1000 + dt
            s.sample_once()
        self.assertEqual(len(calls), 2)


class Idle(Base):
    def test_no_sessions_no_work(self):
        s = self.sampler()
        self.sessions = []
        with mock.patch.object(um, "scan_procs") as sp:
            for _ in range(5):
                self.t[0] += 15
                self.assertEqual(s.sample_once(), 0)
            sp.assert_not_called()
        self.assertLessEqual(s.discovers, 2)      # 75 sn içinde keşif en çok 2 kez
        self.assertFalse(os.path.exists(self.db))

    def test_discover_throttled(self):
        s = self.sampler()
        self.sessions = []
        for _ in range(9):
            self.t[0] += 15
            s.sample_once()
        self.assertLessEqual(s.discovers, 3)

    def test_disabled_never_starts(self):
        with mock.patch.object(um.threading, "Thread") as th:
            self.assertIsNone(um.start_background({"enabled": False, "interval_s": 15, "retention_days": 30}))
            th.assert_not_called()

    def test_config_parsing(self):
        self.assertFalse(um.get_config({"enabled": "off"})["enabled"])
        self.assertTrue(um.get_config({})["enabled"])
        c = um.get_config({"interval_s": "5", "retention_days": "7"})
        self.assertEqual((c["interval_s"], c["retention_days"]), (5.0, 7.0))
        self.assertEqual(um.get_config({"interval_s": "abc"})["interval_s"], 15.0)

    def test_settings_default_key(self):
        from claudeops.settings import DEFAULT_SETTINGS
        self.assertIn("ucli_metrics", DEFAULT_SETTINGS)


class Store(Base):
    def test_retention(self):
        now = 10_000_000.0
        um.write_samples([("a", now - 31 * 86400, 1, 0.0, 0, 0, 1, None), ("a", now - 1 * 86400, 2, 0.0, 0, 0, 1, None)], self.db)
        self.assertEqual(um.prune(30, now, self.db), 1)
        self.assertEqual([x["rss_kib"] for x in um.query("a", path=self.db)["samples"]], [2])

    def test_daily_prune_in_sampler(self):
        fake_proc(self.proc, 10, 1)
        um.write_samples([("old", 1.0, 1, 0.0, 0, 0, 1, None)], self.db)
        self.t[0] = 1000.0 + 40 * 86400
        self.sampler().sample_once(30)
        self.assertEqual([x["name"] for x in um.list_sessions(self.db)], ["u1"])

    def test_wal_and_index(self):
        um.write_samples([("a", 1.0, 1, 0.0, 0, 0, 1, None)], self.db)
        c = um._connect(self.db)
        self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertTrue(c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='samples_session_ts'").fetchone())
        c.close()


class Api(Base):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(um, "db_path", lambda: self.db)
        p.start()
        self.addCleanup(p.stop)
        um.write_samples([("a", float(i), 100 + i, 10.0 * i, 1000 * i, 500 * i, 2, None) for i in range(1, 6)]
                         + [("b", 50.0, 1, 0.0, 0, 0, 1, None)], self.db)

    def test_shape_and_summary(self):
        r = um.api_get("/api/ucli/metrics", {"name": ["a"]})
        self.assertTrue(r["ok"])
        self.assertEqual([s["ts"] for s in r["samples"]], [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(r["summary"], {"rss_max_kib": 105, "cpu_avg": 30.0, "io_r": 4000, "io_w": 2000, "n": 5})
        self.assertEqual(set(r["samples"][0]), {"session", "ts", "rss_kib", "cpu_pct", "io_r", "io_w", "procs", "disk_b"})

    def test_since_limit(self):
        r = um.api_get("/api/ucli/metrics", {"name": ["a"], "since": ["3"], "limit": ["2"]})
        self.assertEqual([s["ts"] for s in r["samples"]], [4.0, 5.0])        # en yeni n, artan sıralı
        self.assertEqual(len(um.api_get("/api/ucli/metrics", {"name": ["a"], "limit": ["99999"]})["samples"]), 5)

    def test_errors_and_empty(self):
        self.assertFalse(um.api_get("/api/ucli/metrics", {})["ok"])
        self.assertFalse(um.api_get("/api/ucli/metrics", {"name": ["a"], "since": ["x"]})["ok"])
        r = um.api_get("/api/ucli/metrics", {"name": ["yok"]})
        self.assertEqual((r["samples"], r["summary"]["n"]), ([], 0))

    def test_sessions(self):
        r = um.api_get("/api/ucli/metrics/sessions", {})
        self.assertEqual([(x["name"], x["last_ts"]) for x in r["sessions"]], [("b", 50.0), ("a", 5.0)])

    def test_authz(self):
        self.assertEqual(authz.action_for("GET", "/api/ucli/metrics"), "status.read")
        self.assertEqual(authz.action_for("GET", "/api/ucli/metrics/sessions"), "status.read")
        self.assertEqual(authz.action_for("POST", "/api/ucli/checks"), "admin.config")      # eski eşleme bozulmadı


class Cost(unittest.TestCase):
    def test_measure_cost_10_children(self):
        kids = [subprocess.Popen(["sleep", "60"]) for _ in range(10)]
        self.addCleanup(lambda: [k.kill() for k in kids])
        td = tempfile.mkdtemp()
        s = um.Sampler(discover=lambda: [("cost", os.getpid(), "")], path=os.path.join(td, "c.db"))
        s.sample_once()
        n = 40
        w0, c0 = time.perf_counter(), time.process_time()
        for _ in range(n):
            s.sample_once()
        wall = (time.perf_counter() - w0) / n * 1000
        cpu = (time.process_time() - c0) / n * 1000
        nproc = len(um.scan_procs())
        print(f"\n[ucli_metrics maliyet] tur: {wall:.1f} ms duvar, {cpu:.1f} ms CPU; 10 çocuk, sistemde {nproc} süreç; "
              f"15 sn aralıkta ~%{cpu / 15000 * 100:.3f} çekirdek")
        last = um.query("cost", path=s.path)["samples"][-1]
        self.assertGreaterEqual(last["procs"], 11)
        self.assertLess(cpu, 500)       # duvar süresi makine yükünü ölçer; maliyet sınırı sürecin CPU süresine


if __name__ == "__main__":
    unittest.main()


class LateSessionTest(unittest.TestCase):
    def test_new_session_found_while_another_runs(self):
        """Bir oturum çalışırken sonradan açılan ikincisi 60 sn içinde keşfedilip örneklenir."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for pid in (101, 102):
                os.makedirs(f"{d}/{pid}")
                open(f"{d}/{pid}/stat", "w").write(f"{pid} (x) S 1 0 0 0 0 0 0 0 0 0 5 5 0 0 20 0 1 0 0 0 0")
                open(f"{d}/{pid}/statm", "w").write("1 100 0 0 0 0 0")
                open(f"{d}/{pid}/io", "w").write("read_bytes: 1\nwrite_bytes: 2\n")
            found = [[("a", 101, "")]]
            clock = [1000.0]
            s = um.Sampler(discover=lambda: list(found[0]), proc_root=d, path=os.path.join(d, "m.db"), now=lambda: clock[0],
                                     disk=lambda c: None)
            s.sample_once()
            found[0] = [("a", 101, ""), ("b", 102, "")]
            clock[0] += 61
            s.sample_once()
            self.assertEqual({r["name"] for r in um.list_sessions(os.path.join(d, "m.db"))}, {"a", "b"})

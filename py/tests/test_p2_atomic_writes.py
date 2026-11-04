"""P2 review bulguları: sabit .tmp yarışı (web_review), models.tsv kilitsiz oku-yaz (close), files.write_text fsync,
steward_quota (_parse_reset ValueError, nan/inf) — stdlib unittest, geçici dizinde.

Çalıştırma:  python3 py/tests/test_p2_atomic_writes.py -v
"""
import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import atomic_json as aj  # noqa: E402
from claudeops import files as files_mod  # noqa: E402
from claudeops import steward_quota as sq  # noqa: E402
from claudeops.commands import close  # noqa: E402
from claudeops.commands import web_review as wr  # noqa: E402


class AtomicWriteTextTest(unittest.TestCase):
    def test_writes_and_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            aj.atomic_write_text(p, "merhaba")
            self.assertEqual(open(p, encoding="utf-8").read(), "merhaba")
            self.assertEqual(os.listdir(d), ["a.txt"])

    def test_tmp_name_is_per_thread(self):
        seen = []
        real_open = os.open

        def spy(path, *a, **k):
            if isinstance(path, str) and path.endswith(".tmp"):     # dizin fsync / .lock açılışları sayılmaz
                seen.append(path)
            return real_open(path, *a, **k)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            with mock.patch.object(aj.os, "open", spy):
                t = threading.Thread(target=aj.atomic_write_text, args=(p, "x"))
                t.start(); t.join()
                aj.atomic_write_text(p, "y")
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1])          # sabit "<path>.tmp" değil
        self.assertTrue(all(s != p + ".tmp" for s in seen))

    def test_concurrent_writers_never_raise(self):
        errs = []
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")

            def w(i):
                try:
                    for _ in range(30):
                        aj.atomic_write_text(p, f"yazar-{i}\n" * 50)
                except Exception as e:      # noqa: BLE001
                    errs.append(e)

            ts = [threading.Thread(target=w, args=(i,)) for i in range(6)]
            [t.start() for t in ts]; [t.join() for t in ts]
            self.assertEqual(errs, [])
            body = open(p, encoding="utf-8").read().splitlines()
            self.assertEqual(len(set(body)), 1)        # tek yazarın tam içeriği, karışık/yarım değil
            self.assertEqual([n for n in os.listdir(d) if n.endswith(".tmp")], [])

    def test_failed_write_removes_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            with mock.patch.object(aj.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    aj.atomic_write_text(p, "x")
            self.assertEqual(os.listdir(d), [])


class WriteLessonTest(unittest.TestCase):
    def test_concurrent_lessons_no_tmp_race_and_no_stale_tmp(self):
        errs = []
        with tempfile.TemporaryDirectory() as d:
            p = SimpleNamespace(root=d)
            target = SimpleNamespace(model="m1")
            # prune her seferinde yeniden yazsın: yazma yolunu zorla
            with mock.patch.object(wr.sl, "prune_lessons", lambda cur: cur + "#"), \
                    mock.patch.object(wr.sw, "log_event", lambda *a, **k: None):
                def w():
                    try:
                        for _ in range(15):
                            wr._write_lesson(p, "proj", target, "failed", "err")
                    except Exception as e:      # noqa: BLE001
                        errs.append(e)
                ts = [threading.Thread(target=w) for _ in range(4)]
                [t.start() for t in ts]; [t.join() for t in ts]
            self.assertEqual(errs, [])
            self.assertEqual([n for n in os.listdir(d) if n.endswith(".tmp")], [])
            self.assertTrue(os.path.exists(os.path.join(d, wr.sl.LESSONS_FILE)))


class CloseModelsTest(unittest.TestCase):
    def _tsv(self, d, text):
        p = os.path.join(d, "models.tsv")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_comment_and_restore(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._tsv(d, "carla\topus\nhc\tsonnet\n")
            with mock.patch.object(close, "MODELS_TSV", p):
                self.assertEqual(close.comment_out_models("carla", False), "commented")
                self.assertEqual(open(p, encoding="utf-8").read(), "#carla\topus\t# CLOSED\nhc\tsonnet\n")
                self.assertEqual(close.comment_out_models("carla", False), "already")
                self.assertEqual(close.uncomment_models("carla"), "restored")
                self.assertEqual(open(p, encoding="utf-8").read(), "carla\topus\nhc\tsonnet\n")

    def test_dry_run_and_missing_do_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._tsv(d, "carla\topus\n")
            before = os.stat(p).st_mtime_ns
            with mock.patch.object(close, "MODELS_TSV", p):
                self.assertEqual(close.comment_out_models("carla", True), "commented")
                self.assertEqual(close.comment_out_models("yok", False), "notfound")
                self.assertEqual(close.uncomment_models("carla", True), "active")
            self.assertEqual(os.stat(p).st_mtime_ns, before)

    def test_missing_file_is_notfound(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(close, "MODELS_TSV", os.path.join(d, "yok.tsv")):
                self.assertEqual(close.comment_out_models("x", False), "notfound")

    def test_concurrent_closes_lose_no_update(self):
        with tempfile.TemporaryDirectory() as d:
            bases = [f"b{chr(97 + i)}" for i in range(8)]
            p = self._tsv(d, "".join(f"{b}\topus\n" for b in bases))
            with mock.patch.object(close, "MODELS_TSV", p):
                ts = [threading.Thread(target=close.comment_out_models, args=(b, False)) for b in bases]
                [t.start() for t in ts]; [t.join() for t in ts]
            lines = open(p, encoding="utf-8").read().splitlines()
            self.assertEqual(len(lines), 8)
            self.assertTrue(all(ln.startswith("#") and ln.endswith("# CLOSED") for ln in lines), lines)


class FilesWriteTextFsyncTest(unittest.TestCase):
    def test_fsync_before_replace(self):
        order = []
        real_fsync, real_replace = os.fsync, os.replace
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "x.txt")
            with open(f, "w") as fh:
                fh.write("eski")
            with mock.patch.object(files_mod, "_writable_roots", return_value=[d]), \
                    mock.patch.object(files_mod, "_resolve_within_roots", return_value=f), \
                    mock.patch.object(files_mod.os, "fsync", lambda fd: order.append("fsync") or real_fsync(fd)), \
                    mock.patch.object(files_mod.os, "replace", lambda a, b: order.append("replace") or real_replace(a, b)):
                r = files_mod.write_text(SimpleNamespace(), f, "yeni")
            self.assertEqual(r, {"ok": True})
            self.assertEqual(order, ["fsync", "replace", "fsync"])   # son fsync = dizin (rename kalıcı)
            self.assertEqual(open(f).read(), "yeni")
            self.assertEqual(os.listdir(d), ["x.txt"])


class QuotaTest(unittest.TestCase):
    def test_parse_reset_invalid_day_returns_none(self):
        self.assertIsNone(sq._parse_reset("Feb 30, 5:59pm", "UTC", 1_700_000_000))

    def test_parse_reset_leap_day_rollover_does_not_raise(self):
        # now = 2025-03-10; "Feb 29" 2025'te yok -> ValueError yerine None
        self.assertIsNone(sq._parse_reset("Feb 29, 5:59pm", "UTC", 1_741_600_000))

    def test_parse_reset_normal(self):
        self.assertIsNotNone(sq._parse_reset("Oct 26, 5:59pm", "UTC", 1_700_000_000))

    def test_num_rejects_nan_inf(self):
        for bad in ("nan", "inf", "-inf"):
            self.assertIsNone(sq._num({"k": bad}, "k", None))
        self.assertEqual(sq._num({"k": "42.5"}, "k", None), 42.5)

    def test_decide_nan_limit_falls_back_to_default_final(self):
        u = sq.Usage(week_pct=96.0)
        d = sq.decide({"mode": "manual", "final_limit": "nan", "manual_limit": "50"}, u, 1_700_000_000)
        self.assertEqual(d.action, "stop")


if __name__ == "__main__":
    unittest.main()

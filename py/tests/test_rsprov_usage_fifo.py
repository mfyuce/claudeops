"""rs-prov TODO (28 Kas edge): `review.usage_summary` ve `ucli_compare._scan` kullanım günlüğünü düz `open` ile açıyordu:
yazanı olmayan FIFO açılışta sonsuza dek bloklar (harcama taraması `_scan_usage_windows` bloklanmaz, `O_NONBLOCK` +
normal dosya denetimi). Kural aynı: normal olmayan dosya atlanır (koşu sayılmaz), tarama sürer. Taramalar ayrı iş
parçacığında, zaman aşımıyla koşar (kırmızıyken test asılmaz). Süreç YOK, geçici dizin."""
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402
from claudeops import ucli_compare as uc  # noqa: E402

REQ = json.dumps({"event": "request", "seconds": 1.0, "t": 1000, "usage": {"prompt_tokens": 7}}) + "\n"


def _within(fn, seconds=5.0):
    out = {}

    def run():
        out["value"] = fn()
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(seconds)
    if th.is_alive():
        # bloklanan açılışı serbest bırak (yazar tarafını açıp kapat) ki iş parçacığı bitsin
        return "blocked"
    return out.get("value")


class _Dir(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = d.name

    def fifo(self, rel):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.mkfifo(path)
        self.addCleanup(self.release, path)
        return path

    @staticmethod
    def release(path):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
        except OSError:
            pass

    def file(self, rel, body):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return path


class UsageSummaryFifoTest(_Dir):
    def test_fifo_is_skipped_and_the_rest_counts(self):
        self.fifo("p/m/model/a/a.usage.jsonl")
        self.file("p/m/model/b/b.usage.jsonl", REQ)
        rows = _within(lambda: rv.usage_summary(self.root))
        self.assertNotEqual(rows, "blocked")
        (row,) = rows
        self.assertEqual((row["runs"], row["requests"]), (1, 1))


class CompareScanFifoTest(_Dir):
    def test_fifo_is_skipped(self):
        out = _within(lambda: uc._scan(self.fifo("s.jsonl")))
        self.assertNotEqual(out, "blocked")
        self.assertEqual(out["requests"], 0)


if __name__ == "__main__":
    unittest.main()

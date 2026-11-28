"""rs-prov TODO (27 Kas edge): `review.usage_summary` ve `ucli_compare._scan` kullanım günlüğünü satır sınırı olmadan
okuyordu (tek dev satır belleğe alınır) ve derin iç içe satırda `json.loads` `RecursionError` ile taramayı düşürüyordu.
Kural, harcama taramasıyla (`review._usage_lines`, `_MAX_LINE_BYTES`, `_MAX_LINE_DEPTH`) aynı: aşan satır atlanır,
sonraki satırlar sayılır. Süreç YOK, geçici dizin."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402
from claudeops import ucli_compare as uc  # noqa: E402

REQ = {"event": "request", "seconds": 1.0, "t": 1000, "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
LONG = dict(REQ, pad="x" * 200)
DEEP = "[" * 100_000 + "]" * 100_000


class _Dir(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = d.name
        for p in (mock.patch.object(rv, "_MAX_LINE_BYTES", 128), mock.patch.object(rv, "_log_bad", lambda *a: None)):
            p.start()
            self.addCleanup(p.stop)

    def write(self, rel, lines):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join((ln if isinstance(ln, str) else json.dumps(ln)) + "\n" for ln in lines))
        return path


class UsageSummaryTest(_Dir):
    def rows(self, lines):
        self.write("p/m/model/ts/ts.usage.jsonl", lines)
        (row,) = rv.usage_summary(self.root)
        return row

    def test_overlong_line_is_skipped_and_the_rest_counts(self):
        row = self.rows([LONG, REQ])
        self.assertEqual((row["runs"], row["requests"], row["prompt_tokens"]), (1, 1, 7))

    def test_deep_line_does_not_break_the_scan(self):
        with mock.patch.object(rv, "_MAX_LINE_BYTES", 1 << 20):
            row = self.rows([DEEP, REQ])
        self.assertEqual((row["requests"], row["prompt_tokens"]), (1, 7))


    def test_carriage_returns_still_separate_records(self):
        path = self.write("p/m/model/ts/ts.usage.jsonl", [])
        with open(path, "wb") as f:
            f.write((json.dumps(REQ) + "\r" + json.dumps(REQ) + "\r\n" + json.dumps(REQ) + "\n").encode())
        with mock.patch.object(rv, "_MAX_LINE_BYTES", 1 << 20):
            (row,) = rv.usage_summary(self.root)
        self.assertEqual(row["requests"], 3)


class CompareScanTest(_Dir):
    def test_overlong_line_is_skipped_and_the_rest_counts(self):
        out = uc._scan(self.write("s.jsonl", [LONG, REQ]))
        self.assertEqual((out["requests"], out["tokens"]["in"]), (1, 7))

    def test_deep_line_does_not_break_the_scan(self):
        with mock.patch.object(rv, "_MAX_LINE_BYTES", 1 << 20):
            out = uc._scan(self.write("s.jsonl", [DEEP, REQ]))
        self.assertEqual((out["requests"], out["tokens"]["in"]), (1, 7))


if __name__ == "__main__":
    unittest.main()

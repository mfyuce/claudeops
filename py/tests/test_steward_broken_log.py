"""Bozuk günlük kaydı/sayısı: `dry_report`, `summary_text`, `compact_log` düşmez, veriyi bozmaz (kapalı yön)."""
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import periodic, steward as sw  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402

D = "2026-11-20"
BAD_NUMBERS = ("çok", [1], {"a": 1}, float("inf"), float("nan"))


def _line(**kw):
    return (json.dumps(kw, ensure_ascii=False) + "\n").encode()


def _would(**kw):
    return _line(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), event="would:keepwarm", **kw)


class _Log(_Tmp):
    def write_log(self, data: bytes):
        path = sw._pp(None).log
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path


class DryReportTest(_Log):
    def test_non_dict_line_skipped(self):
        self.write_log(_would(name="a") + b'["\\"would:x"]\n' + b'"x \\"would:"\n["would:"]\n' + _would(name="b"))
        self.assertEqual(sw.dry_report()["keepwarm"]["names"], {"a": 1, "b": 1})

    def test_bad_chars_counts_zero(self):
        self.write_log(b"".join(_would(name="a", chars=v) for v in BAD_NUMBERS) + _would(name="a", chars=7))
        r = sw.dry_report()["keepwarm"]
        self.assertEqual((r["count"], r["chars"], r["names"]), (len(BAD_NUMBERS) + 1, 7, {"a": len(BAD_NUMBERS) + 1}))

    def test_invalid_utf8_line_skipped(self):
        bad = _would(name="x").replace(b'"x"', b'"\xff"')
        self.write_log(_would(name="a") + bad + _would(name="b"))
        self.assertEqual(sw.dry_report()["keepwarm"]["names"], {"a": 1, "b": 1})


class SummaryTextTest(_Log):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(periodic, "orphan_summary", return_value={})
        p.start()
        self.addCleanup(p.stop)

    def good(self):
        return _line(ts=f"{D}T01:00:00", event="tick", trigger="timer", mode="act")

    def test_non_dict_record_skipped(self):
        self.write_log(self.good() + f'[{{"ts": "{D}T00:00:00"}}]\n'.encode())
        self.assertEqual([e["event"] for e in sw.log_entries_for_date(D)], ["tick"])
        self.assertIn("- Tick: 1", sw.summary_text(D))

    def test_daily_summary_skips_non_dict(self):
        entries = [["x"], "metin", None, 3, {"ts": f"{D}T01:00:00", "event": "tick", "trigger": "timer"}]
        self.assertIn("- Tick: 1", sw.daily_summary(entries, D))

    def test_invalid_utf8_line_skipped(self):
        self.write_log(self.good() + _line(ts=f"{D}T02:00:00", event="tick", x="y").replace(b'"y"', b'"\xff"'))
        self.assertEqual(len(sw.log_entries_for_date(D)), 1)
        self.assertIn("- Tick: 1", sw.summary_text(D))
        self.assertEqual(sw.missed_summary_dates(time.mktime((2026, 11, 21, 12, 0, 0, 0, 0, -1)), 1), [D])

    def test_day_with_only_broken_records_is_not_missed(self):
        self.write_log(f'[{{"ts": "{D}T00:00:00"}}]\n'.encode())
        self.assertEqual(sw.missed_summary_dates(time.mktime((2026, 11, 21, 12, 0, 0, 0, 0, -1)), 1), [])

    def test_bad_pending_items_is_zero(self):
        self.write_log(self.good())
        for value in BAD_NUMBERS:
            with self.subTest(value):
                sw.save_state({"pending_items": value})
                self.assertIn("0 gözden geçirme maddesi", sw.summary_text(D))

    def test_bad_numbers_in_records_are_zero(self):
        for value in BAD_NUMBERS:
            with self.subTest(value):
                self.write_log(self.good()
                               + _line(ts=f"{D}T23:59:59", event="ticks", n=value, manual=value, errors=value)
                               + _line(ts=f"{D}T03:00:00", event="review_store_held", n=value, files=5))
                text = sw.summary_text(D)
                self.assertIn("- Tick: 1\n", text)
                self.assertIn("dışarıda kalan dosya: 0 ()", text)


class CompactLogTest(_Log):
    def test_invalid_utf8_leaves_file_untouched(self):
        data = _line(ts=f"{D}T01:00:00", event="tick", trigger="timer") + b"bozuk \xff\n"
        path = self.write_log(data)
        before = os.stat(path)
        self.assertEqual(sw.compact_log(D), 0)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), data)
        after = os.stat(path)
        self.assertEqual((after.st_ino, after.st_mtime_ns), (before.st_ino, before.st_mtime_ns))


if __name__ == "__main__":
    unittest.main()

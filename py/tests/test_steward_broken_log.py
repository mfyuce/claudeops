"""Bozuk günlük kaydı/sayısı: `dry_report`, `summary_text`, `compact_log` düşmez, veriyi bozmaz (kapalı yön)."""
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import session_usage as su  # noqa: E402


def _row(mid, model="claude-sonnet-5-5", i=10, cw=100, cr=1000, out=5, rid=None, typ="assistant"):
    return json.dumps({"type": typ, "uuid": f"u-{mid}-{out}-{time.time_ns()}", "requestId": rid or f"req-{mid}",
                       "message": {"id": mid, "model": model,
                                   "usage": {"input_tokens": i, "cache_creation_input_tokens": cw,
                                             "cache_read_input_tokens": cr, "output_tokens": out}}}) + "\n"


class SessionUsageTest(unittest.TestCase):
    def setUp(self):
        su._files.clear()
        su._summaries.clear()
        self.tmp = tempfile.TemporaryDirectory()   # gerçek ~/.claude/projects'e DOKUNMAZ
        self.addCleanup(self.tmp.cleanup)
        self.main = os.path.join(self.tmp.name, "sid1.jsonl")
        os.makedirs(os.path.join(self.tmp.name, "sid1", "subagents"))

    def _sub(self, name, text):
        with open(os.path.join(self.tmp.name, "sid1", "subagents", name), "w") as f:
            f.write(text)

    def test_main_and_subagents_separate_with_family_breakdown(self):
        with open(self.main, "w") as f:
            f.write(_row("m1"))
            f.write(_row("m2", model="claude-fable-5-1", i=1, cw=2, cr=3, out=4))
            f.write(json.dumps({"type": "user", "message": {"content": "x"}}) + "\n")
        self._sub("agent-a.jsonl", _row("s1", model="claude-haiku-5", i=7, cw=0, cr=50, out=9))
        self._sub("agent-b.jsonl", _row("s2", model="mystery", i=1, cw=1, cr=1, out=1))
        u = su.usage_for_path(self.main)
        self.assertEqual((u["in"], u["out"], u["cache_write"], u["cache_read"], u["turns"]), (11, 9, 102, 1003, 2))
        s = u["subagents"]
        self.assertEqual((s["n"], s["in"], s["out"], s["cache_write"], s["cache_read"], s["turns"]), (2, 8, 10, 1, 51, 2))
        self.assertEqual(sorted(u["by_family"]), ["fable", "haiku", "other", "sonnet"])
        self.assertEqual(u["by_family"]["haiku"]["cache_read"], 50)

    def test_split_rows_of_one_reply_counted_once_and_max_kept(self):
        with open(self.main, "w") as f:
            for _ in range(3):                      # thinking/text/tool_use bölünmesi: aynı id+requestId, aynı usage
                f.write(_row("m1", out=50))
        self._sub("agent-a.jsonl", _row("s1", out=2) + _row("s1", out=40) + _row("s1", out=40))
        u = su.usage_for_path(self.main)
        self.assertEqual((u["turns"], u["out"], u["in"]), (1, 50, 10))
        self.assertEqual((u["subagents"]["turns"], u["subagents"]["out"]), (1, 40))

    def test_bad_lines_skipped(self):
        with open(self.main, "w") as f:
            f.write("{bozuk json \"usage\"\n")
            f.write(json.dumps({"type": "assistant", "message": {"id": "x", "usage": "string"}}) + "\n")
            f.write(_row("m1"))
        self.assertEqual(su.usage_for_path(self.main)["turns"], 1)

    def test_incremental_append_truncate_and_partial_last_line(self):
        with open(self.main, "w") as f:
            f.write(_row("m1", out=5))
        self.assertEqual(su.usage_for_path(self.main)["out"], 5)
        first_offset = su._files[self.main]["offset"]
        partial = _row("m2", out=7)
        with open(self.main, "a") as f:
            f.write(partial[:-30])                  # yazım sürüyor: yarım satır
        self.assertEqual(su.usage_for_path(self.main)["turns"], 1)
        self.assertEqual(su._files[self.main]["offset"], first_offset)
        with open(self.main, "a") as f:
            f.write(partial[-30:])                  # tamamlandı
        u = su.usage_for_path(self.main)
        self.assertEqual((u["turns"], u["out"]), (2, 12))
        # yalnız eklenen kısım okunur: ikinci hesap dosyayı baştan AÇMAZ
        real_open = open
        seen = []

        def spy(path, mode="r", *a, **k):
            fh = real_open(path, mode, *a, **k)
            if str(path) == self.main and "b" in mode:
                orig = fh.seek
                fh.seek = lambda off, *x: (seen.append(off), orig(off, *x))[1]
            return fh
        with open(self.main, "a") as f:
            f.write(_row("m3", out=1))
        with mock.patch("builtins.open", spy):
            su.usage_for_path(self.main)
        self.assertTrue(seen and seen[0] > 0)
        # kesilme: dosya küçüldü, baştan okunur
        with open(self.main, "w") as f:
            f.write(_row("z1", out=3))
        u = su.usage_for_path(self.main)
        self.assertEqual((u["turns"], u["out"]), (1, 3))

    def test_missing_file_returns_none_never_raises(self):
        self.assertIsNone(su.usage_for_path(os.path.join(self.tmp.name, "yok.jsonl")))
        self.assertIsNone(su.usage_for_path(None))

    def test_cached_returns_none_first_then_value_after_background_refresh(self):
        with open(self.main, "w") as f:
            f.write(_row("m1"))
        self.assertIsNone(su.cached_usage_for_path(self.main))
        deadline = time.time() + 5
        v = None
        while v is None and time.time() < deadline:
            time.sleep(0.02)
            v = su.cached_usage_for_path(self.main)
        self.assertEqual(v["turns"], 1)

    def test_fmt_tokens(self):
        self.assertEqual([su.fmt_tokens(n) for n in (5, 12345, 1234567)], ["5", "12.3K", "1.23M"])


if __name__ == "__main__":
    unittest.main()

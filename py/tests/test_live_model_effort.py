"""Canlı model/effort testleri (stdlib unittest, ek bağımlılık yok).

Çalıştırma:  python3 py/tests/test_live_model_effort.py -v

Kapsadığı hata (TODO.md 2026-10-09): tablo, çalışan session'ın cmdline'daki SPAWN-ANI
modelini gösteriyordu (vc20261008 tabloda haiku, süreç 127 turdur sonnet-5-5). Düzeltme:
jsonl'daki canlı değer, ama (1) yalnız bu süreç başladıktan sonra yazılmış satırlar
(resume'da jsonl'ın son turu önceki sürecinki), (2) yalnız `<sid>.jsonl` tam eşleşirse,
(3) dosya değişmediyse yeniden okunmaz. Gerçek session'lara / dosyalara DOKUNMAZ.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402

START = 1_800_000_000.0  # sahte "süreç başlangıcı" (epoch saniye)


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def assistant(epoch, model, effort=None, with_ts=True):
    obj = {"type": "assistant", "message": {"model": model}}
    if with_ts:
        obj["timestamp"] = iso(epoch)
    if effort:
        obj["effort"] = effort
    return obj


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "timestamp": iso(START - 500)}) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")


class TmpDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def jsonl(self, rows, name="sid-1.jsonl"):
        p = self.dir / name
        write_jsonl(p, rows)
        return p


class LastAssistantSinceTests(TmpDirCase):
    def test_since_returns_only_rows_written_after_the_process_started(self):
        p = self.jsonl([assistant(START - 100, "claude-sonnet-5", "max"),
                        assistant(START + 50, "claude-sonnet-5-5", "high")])
        self.assertEqual(cp.last_assistant_model(p, since=START), "claude-sonnet-5-5")
        self.assertEqual(cp.last_assistant_effort(p, since=START), "high")

    def test_only_previous_incarnation_rows_means_unknown(self):
        """Resume sonrası ilk tura kadar: jsonl'daki son tur önceki sürecinki."""
        p = self.jsonl([assistant(START - 100, "claude-sonnet-5-5", "max")])
        self.assertIsNone(cp.last_assistant_model(p, since=START))
        self.assertIsNone(cp.last_assistant_effort(p, since=START))

    def test_without_since_behaviour_is_unchanged(self):
        p = self.jsonl([assistant(START - 100, "claude-sonnet-5-5", "max")])
        self.assertEqual(cp.last_assistant_model(p), "claude-sonnet-5-5")
        self.assertEqual(cp.last_assistant_effort(p), "max")

    def test_row_without_timestamp_is_not_treated_as_old(self):
        p = self.jsonl([assistant(START + 10, "claude-sonnet-5"),
                        assistant(0, "claude-opus-5-5", with_ts=False)])
        self.assertEqual(cp.last_assistant_model(p, since=START), "claude-opus-5-5")

    def test_scan_stops_at_the_first_older_row(self):
        """Geriye doğru okunur: bundan önceki satırların hepsi daha da eski sayılır."""
        p = self.jsonl([assistant(START + 10, "claude-sonnet-5"), assistant(START - 10, "claude-haiku-5-5")])
        self.assertIsNone(cp.last_assistant_model(p, since=START))


class LiveModelEffortTests(TmpDirCase):
    def setUp(self):
        super().setUp()
        web._LIVE_VALUES_CACHE.clear()
        self.addCleanup(web._LIVE_VALUES_CACHE.clear)

    def sess(self, **kw):
        base = dict(name="vc", cli="claude", sid="sid-1", pid=4242, cwd="/w/p",
                    model="claude-haiku-5-5", effort="max")
        base.update(kw)
        return SimpleNamespace(**base)

    def run_live(self, s, path, started=START):
        with mock.patch.object(web, "jsonl_path_for", lambda cwd, sid: path), \
             mock.patch.object(web, "_process_started_at", lambda pid: started):
            return web._live_model_effort(s)

    def test_live_values_written_by_this_process_replace_cmdline_values(self):
        p = self.jsonl([assistant(START + 5, "claude-sonnet-5-5", "high")])
        self.assertEqual(self.run_live(self.sess(), p), ("claude-sonnet-5-5", "high"))

    def test_fresh_resume_without_a_turn_keeps_cmdline_values(self):
        p = self.jsonl([assistant(START - 60, "claude-sonnet-5-5", "high")])  # önceki sürecin turu
        self.assertEqual(self.run_live(self.sess(), p), ("claude-haiku-5-5", "max"))

    def test_effort_missing_in_live_rows_falls_back_per_field(self):
        p = self.jsonl([assistant(START + 5, "claude-sonnet-5-5")])
        self.assertEqual(self.run_live(self.sess(), p), ("claude-sonnet-5-5", "max"))

    def test_another_sessions_file_is_ignored(self):
        p = self.jsonl([assistant(START + 5, "claude-opus-5-5", "low")], name="someone-else.jsonl")
        self.assertEqual(self.run_live(self.sess(), p), ("claude-haiku-5-5", "max"))

    def test_non_claude_and_sidless_sessions_never_touch_the_file(self):
        p = self.dir / "never-created.jsonl"
        self.assertEqual(self.run_live(self.sess(cli="agy", model="gemini-3.1-pro-high", effort=None), p),
                         ("gemini-3.1-pro-high", None))
        self.assertEqual(self.run_live(self.sess(sid=None), p), ("claude-haiku-5-5", "max"))

    def test_unknown_process_start_falls_back(self):
        p = self.jsonl([assistant(START + 5, "claude-sonnet-5-5", "high")])
        self.assertEqual(self.run_live(self.sess(), p, started=None), ("claude-haiku-5-5", "max"))

    def test_unchanged_file_is_not_reread_and_changed_file_is_(self):
        p = self.jsonl([assistant(START + 5, "claude-sonnet-5-5", "high")])
        calls = []
        real = cp.last_assistant_model

        def counting(path, since=None):
            calls.append(path)
            return real(path, since=since)

        with mock.patch.object(web, "last_assistant_model", counting):
            self.assertEqual(self.run_live(self.sess(), p)[0], "claude-sonnet-5-5")
            self.assertEqual(self.run_live(self.sess(), p)[0], "claude-sonnet-5-5")
            self.assertEqual(len(calls), 1)  # ikinci çağrı önbellekten
            with open(p, "a", encoding="utf-8") as f:  # yeni tur: boyut/mtime değişir
                f.write(json.dumps(assistant(START + 9, "claude-opus-5-5", "max")) + "\n")
            self.assertEqual(self.run_live(self.sess(), p)[0], "claude-opus-5-5")
            self.assertEqual(len(calls), 2)

    def test_read_error_falls_back_and_does_not_raise(self):
        with mock.patch.object(web, "jsonl_path_for", side_effect=OSError("disk")):
            self.assertEqual(web._live_model_effort(self.sess()), ("claude-haiku-5-5", "max"))


class LiveModelEndpointTests(TmpDirCase):
    """`POST /api/live-model` / `/api/live-effort` (Terminal→Bilgi sekmesi) tabloyla AYNI kuralı kullanır."""

    def call(self, fn, rows, started=START):
        p = self.jsonl(rows)
        s = SimpleNamespace(name="vc", cli="claude", sid="sid-1", pid=4242, cwd="/w/p", model="m", effort="e")
        with mock.patch.object(web, "_find_running_for_action", lambda name: ("exact", [s])), \
             mock.patch.object(web, "_fleet_status", lambda: {}), \
             mock.patch.object(web, "jsonl_path_for", lambda cwd, sid: p), \
             mock.patch.object(web, "_process_started_at", lambda pid: started):
            return fn("vc")

    def test_live_model_ignores_previous_incarnation(self):
        old = [assistant(START - 60, "claude-sonnet-5-5", "max")]
        self.assertEqual(self.call(web._live_model, old),
                         {"ok": True, "available": False, "reason": "no_assistant_turn"})
        new = old + [assistant(START + 5, "claude-sonnet-5", "high")]
        self.assertEqual(self.call(web._live_model, new), {"ok": True, "available": True, "model": "claude-sonnet-5"})

    def test_live_effort_ignores_previous_incarnation(self):
        old = [assistant(START - 60, "claude-sonnet-5-5", "max")]
        self.assertEqual(self.call(web._live_effort, old),
                         {"ok": True, "available": False, "reason": "no_assistant_turn"})
        new = old + [assistant(START + 5, "claude-sonnet-5", "high")]
        self.assertEqual(self.call(web._live_effort, new), {"ok": True, "available": True, "effort": "high"})


if __name__ == "__main__":
    unittest.main()

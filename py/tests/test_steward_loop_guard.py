"""L4 (10 Kas 2026): genel döngü kesici + aynı içerikli log satırı tekilleştirme."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402


def view(name, text="yapacak iş yok", running=True):
    return sw.SessionView(name=name, running=running, last_assistant=text)


class LoopGuardTest(unittest.TestCase):
    def _run(self, n, views_fn, kind="idle_nudge", name="danisppr", t0=1000.0, step=60.0, st=None):
        st = st or {}
        outs = []
        for i in range(n):
            acts, st = sw.loop_guard([sw.Action(kind, name, "devam")], views_fn(i), st, t0 + i * step)
            outs.append(acts)
        return outs, st

    def test_repeats_without_change_break_once_then_pause(self):
        outs, st = self._run(sw.LOOP_MAX + 3, lambda i: [view("danisppr")])
        kinds = [[a.kind for a in o] for o in outs]
        self.assertTrue(all(k == ["idle_nudge"] for k in kinds[:sw.LOOP_MAX]))
        self.assertEqual(kinds[sw.LOOP_MAX], ["loop_break"])          # tek bildirim
        self.assertEqual(kinds[sw.LOOP_MAX + 1:], [[], []])           # duraklatıldı, sessiz
        self.assertEqual([e["name"] for e in sw.loop_paused(st, 1000.0 + 20 * 60)], ["danisppr"])
        # duraklama bitince yeniden sayılır
        acts, st = sw.loop_guard([sw.Action("idle_nudge", "danisppr", "devam")], [view("danisppr")], st,
                                 1000.0 + sw.LOOP_PAUSE_SECONDS + 3600)
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])

    def test_progress_resets_counter(self):
        outs, _ = self._run(sw.LOOP_MAX * 3, lambda i: [view("p", text=f"adım {i}")], kind="directive", name="p")
        self.assertTrue(all([a.kind for a in o] == ["directive"] for o in outs))

    def test_failing_start_on_absent_session_breaks(self):
        outs, _ = self._run(sw.LOOP_MAX + 1, lambda i: [], kind="start", name="vc")      # açılamıyor: hep yok
        self.assertEqual([a.kind for a in outs[-1]], ["loop_break"])

    def test_other_kinds_untouched(self):
        acts, st = sw.loop_guard([sw.Action("ask_user", "p", "x"), sw.Action("idea", "", "y")], [], {}, 1.0)
        self.assertEqual([a.kind for a in acts], ["ask_user", "idea"])
        self.assertNotIn("loop_guard", st)


class LogDedupTest(unittest.TestCase):
    def setUp(self):
        sw._LOG_SEEN.clear()
        self.addCleanup(sw._LOG_SEEN.clear)

    def test_identical_events_within_window_are_suppressed_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "log.jsonl")
            with mock.patch.object(sw, "_pp", lambda p=None: mock.Mock(log=log)), mock.patch.object(sw.time, "time") as tt:
                tt.return_value = 1000.0
                for _ in range(5):
                    sw.log_event("review_copy_not_ready", project="a", error="x")
                sw.log_event("review_copy_not_ready", project="b", error="x")     # farklı içerik: yazılır
                sw.log_event("tick", n=0)
                sw.log_event("tick", n=0)                                          # tick muaf
                tt.return_value = 1000.0 + sw.LOG_DEDUP_SECONDS + 1
                sw.log_event("review_copy_not_ready", project="a", error="x")
            with open(log) as f:
                rows = [json.loads(l) for l in f]
        a = [r for r in rows if r.get("project") == "a"]
        self.assertEqual(len(a), 2)
        self.assertNotIn("repeated", a[0])
        self.assertEqual(a[1]["repeated"], 4)
        self.assertEqual(sum(1 for r in rows if r["event"] == "tick"), 2)
        self.assertEqual(sum(1 for r in rows if r.get("project") == "b"), 1)


if __name__ == "__main__":
    unittest.main()

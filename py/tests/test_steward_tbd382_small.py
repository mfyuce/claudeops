"""TBD#382 (2-7): beyin araç hükmü, onay sözcüğü, teslim sınırı, saat okuyan iki yer, İngilizce tur maddesi metinleri."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw, steward_ask  # noqa: E402


def _view(name, **kw):
    base = dict(running=True, cwd="/tmp/x", cli="claude", busy=False, history_size=100, tmux=True,
                started_at=1000.0, last_activity=1000.0)
    base.update(kw)
    return sw.SessionView(name=name, **base)


class BrainToolsMissingTest(unittest.TestCase):
    def test_ordinary_sentence_is_not_a_report(self):
        for t in ("Nothing to do: no tools needed.", "No tool is needed for this item.", "no tools are required here",
                  "No tools were needed this turn.", "No tool calls needed.", "no tool calls are necessary",
                  "no deferred tools needed", "No tool use required.", "no tools will be needed"):
            with self.subTest(t):
                self.assertFalse(sw.brain_tools_missing_text(t))

    def test_real_reports_still_detected(self):
        for t in ("No matching deferred tools found", "no tools available", "I have no tools in this session.",
                  "There are no tools I can call.", "no deferred tools", "No tools. I cannot proceed.",
                  "tools are not available", "the steward MCP server is not connected", "steward_overview araçları yok",
                  "karar veremedim", "I see no tools, which are needed for this tour.",
                  "No tools needed yesterday, but today the steward tools are unavailable."):
            with self.subTest(t):
                self.assertTrue(sw.brain_tools_missing_text(t))


class UpperTierApprovedTest(unittest.TestCase):
    def _approved(self, answer):
        tag = sw.upper_tier_tag("a", "claude-opus", "high")
        q = sw.Question(id="q1", project="a", text=f"{tag} onay?", created_at=1.0, status="answered", answer=answer,
                        source=sw.UPPER_MODEL_SOURCE)
        return sw.upper_tier_approved([q], "a", "claude-opus", "high")

    def test_space_before_punctuation(self):
        for a in ("evet .", "onayla !", "Evet . !", "approve  !!", "yes ...", "evet\n.", "onay! ", "evet.", "EVET"):
            with self.subTest(a):
                self.assertTrue(self._approved(a))

    def test_non_approval_stays_non_approval(self):
        for a in ("hayır .", "evet değil .", "evet ama bekle !", ". evet", "onaylamıyorum .", " . ", "!", "evet ?",
                  "ev et .", "evet,"):
            with self.subTest(a):
                self.assertFalse(self._approved(a))


class PlanDeliveriesLimitTest(unittest.TestCase):
    def test_non_positive_limit_yields_nothing(self):
        for limit in (0, -1):
            taken, state = set(), {"last_directive_at": {"b": 5.0}}
            out, st = sw.plan_deliveries([("a", lambda v: sw.Action("nudge", v.name, "x", {}))], [_view("a", blueprint="a")],
                                         taken, state, 100.0, limit)
            self.assertEqual((out, st, taken), ([], state, set()))

    def test_positive_limit_unchanged(self):
        out, st = sw.plan_deliveries([("a", lambda v: sw.Action("nudge", v.name, "x", {}))], [_view("a", blueprint="a")],
                                     set(), {}, 100.0, 1)
        self.assertEqual([a.name for a in out], ["a"])
        self.assertEqual(st["last_directive_at"], {"a": 100.0})


class PlanMarkersClockTest(unittest.TestCase):
    def test_uses_module_clock(self):
        projects = {"a": sw.Project(name="a")}
        with mock.patch.object(sw, "_now", return_value=1234.5):
            _, st = sw.plan_markers([_view("a", blueprint="a", last_assistant="STEWARD-NEXT: test yaz")], projects, {},
                                    sw.Config(enabled=True))
        self.assertEqual(st["project_next"]["a"]["at"], 1234.5)


class OwnerClassZeroNowTest(unittest.TestCase):
    def test_zero_now_is_not_replaced_by_the_clock(self):
        q = sw.Question(id="q1", project="a", text="hangi sıra?", created_at=0.0, deferred_until=100.0)
        self.assertEqual(steward_ask.owner_class(q, now=0.0), "deferred")

    def test_none_reads_the_clock(self):
        q = sw.Question(id="q1", project="a", text="hangi sıra?", created_at=0.0, deferred_until=100.0)
        with mock.patch.object(steward_ask.time, "time", return_value=50.0):
            self.assertEqual(steward_ask.owner_class(q), "deferred")
        with mock.patch.object(steward_ask.time, "time", return_value=200.0):
            self.assertEqual(steward_ask.owner_class(q), "")


class ReviewItemsLanguageTest(unittest.TestCase):
    def _items(self, lang):
        now = 100000.0
        projects = {"a": sw.Project(name="a", phase="planned")}
        qs = [sw.Question(id="r1", project="a", text="which order?", created_at=now - 3600, routine=True, source="a"),
              sw.Question(id="r2", project="a", text="which model?", created_at=now - 60, routine=True),
              sw.Question(id="o1", project="b", text="which name?", created_at=now - 7200, options=["x", "y"]),
              sw.Question(id="d1", project="zz", text="done?", created_at=now - 60, status="answered", answer="go",
                          answered_at=now - 30)]
        projects["b"] = sw.Project(name="b", phase="planned")
        cfg = sw.Config(enabled=True, ask_gate="shadow", lang=lang)
        v = _view("a", blueprint="a", last_assistant="STEWARD-NEXT: write tests", last_activity=1000.0)
        with mock.patch.object(steward_ask, "tour_eligible", side_effect=lambda q, *a, **k: q.id == "o1"):
            items = sw.review_items([v], projects, cfg, now, qs, [])
        return {(i["kind"], i.get("id", "")): i for i in items}

    def test_english_panel(self):
        items = self._items("en")
        self.assertEqual(items[("routine", "r1")]["text"],
                         "Routine question [r1] (answer it with steward_answer id answer) "
                         "[asked 60 min ago: still waiting, do it first]: which order?")
        self.assertEqual(items[("routine", "r2")]["text"],
                         "Routine question [r2] (answer it with steward_answer id answer): which model?")
        self.assertEqual(items[("ask", "o1")]["text"],
                         "Owner question [o1] (steward_answer id answer; your answer passes through the gate, skip it if unsure): "
                         "which name?\nOptions: x | y")
        self.assertEqual(items[("blocked", "d1")]["text"], "Answered question [d1]: done?\nAnswer: go")
        self.assertEqual(items[("idle", "")]["contradictions"],
                         ["the session reported UNOWNED work with STEWARD-NEXT: «write tests». Do not skip it as 'no new unowned "
                          "work': if no pending owner answer blocks it, keep the session on it with steward_directive."])

    def test_turkish_panel_unchanged(self):
        items = self._items("tr")
        self.assertEqual(items[("routine", "r1")]["text"],
                         "Rutin soru [r1] (steward_answer id cevap ile cevapla) [60 dk önce soruldu: beklemede, öncelik ver]: "
                         "which order?")
        self.assertEqual(items[("blocked", "d1")]["text"], "Cevaplanan soru [d1]: done?\nCevap: go")
        self.assertIn("SAHİPSİZ iş bildirdi: «write tests»", items[("idle", "")]["contradictions"][0])


if __name__ == "__main__":
    unittest.main()

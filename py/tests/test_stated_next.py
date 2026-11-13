"""Oturumun yanıtındaki gerçek STEWARD-NEXT: keepwarm 'ok' yerine `devam: <iş>`, idle_nudge TODO/not boş olsa da ve ASK işareti olsa da gider,
beyin turu maddesinde NEXT + çelişki uyarısı (prompti 13 Kas 22:00/22:52: keepwarm 'ok' yazdırdı, idle_nudge hiç koşmadı, beyin 'iş yok' dedi)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops import steward_keepwarm as skw  # noqa: E402

NOW = 1_000_000.0
REAL = ("Ölçüm kuralı için sahip cevabı bekliyor.\nSTEWARD-ASK: PE2 payda seçimi hangisi? seçenekler: a, b. öneri: a\n"
        "STEWARD-NEXT: PE2 ölçüm kuralını netleştir, ölçüm betiği, Agent-Sentry PDF teyidi")
NONE = "Her şey sahipte.\nSTEWARD-NEXT: yok"


def _view(txt=REAL, **kw):
    base = dict(running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=1.0, last_activity=NOW - 3100,
                last_assistant=txt, context_tokens=119000)
    base.update(kw)
    return sw.SessionView(name="p", **base)


class Helper(unittest.TestCase):
    def test_marker_next_work(self):
        self.assertTrue(sw.marker_next_work(REAL).startswith("PE2 ölçüm kuralını"))
        for t in (NONE, "", "iş bitti", "STEWARD-NEXT: bitti", "STEWARD-NEXT: sahip cevap verirse X'e geç"):
            self.assertEqual(sw.marker_next_work(t), "", t)


class Keepwarm(unittest.TestCase):
    def test_keepwarm_sends_devam_with_next_not_ok(self):
        pr = sw.Project(name="p", phase="planned", cadence_minutes=0, notes="")
        self.assertEqual(skw.keepwarm_text(pr, _view()).split(":")[0], "devam")
        self.assertIn("Agent-Sentry", skw.keepwarm_text(pr, _view()))
        self.assertEqual(skw.keepwarm_text(pr, _view(NONE)), skw.KEEPWARM_TEXT)      # NEXT yok: eski davranış
        self.assertEqual(skw.keepwarm_text(pr, _view("tur hata ile bitti API Error: 500\nSTEWARD-NEXT: x")).startswith("devam"), False)


class IdleNudge(unittest.TestCase):
    def plan(self, views, n_open=0, mode="act", state=None):
        projs = {"p": sw.Project(name="p", phase="planned", cadence_minutes=0)}
        cfg = sw.Config(enabled=True, mode="act", claude_idle=mode)
        return sw.plan_claude_idle(views, projs, state or {}, cfg, NOW, [], open_work=lambda _p: n_open, owner_todo=lambda _p: 0,
                                   todo_sha=lambda _p: "")

    def test_nudges_with_stated_next_even_with_empty_todo_and_ask_marker(self):
        acts, st = self.plan([_view()])
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])
        self.assertTrue(acts[0].payload["text"].startswith("devam: PE2 ölçüm"))
        self.assertEqual(st["claude_idle"]["p"]["n"], 1)

    def test_no_next_empty_todo_no_nudge_as_before(self):
        self.assertEqual(self.plan([_view(NONE)])[0], [])
        self.assertEqual(self.plan([_view("STEWARD-ASK: soru? öneri: a")])[0], [])

    def test_chain_limit_still_applies(self):
        _, st = self.plan([_view()])
        cfg_max = sw.Config().ucli_idle_max_consecutive
        st["claude_idle"]["p"]["n"] = cfg_max
        st["claude_idle"]["p"]["at"] = NOW - 10
        self.assertEqual(self.plan([_view(last_activity=NOW - 3100)], state=st)[0], [])


class TourItem(unittest.TestCase):
    def test_prompt_shows_stated_next_and_contradiction(self):
        it = {"kind": "idle", "name": "p", "idle_minutes": 50, "stated_next": "PE2 ölçüm kuralı",
              "contradictions": ["oturum STEWARD-NEXT ile SAHİPSİZ iş bildirdi: «PE2 ölçüm kuralı»."],
              "last_exchange": {"assistant": "x" * 900}}
        p = sw.build_tour_prompt([it])
        self.assertIn("STEWARD-NEXT): PE2 ölçüm kuralı", p)
        self.assertIn("SAHİPSİZ iş bildirdi", p)


if __name__ == "__main__":
    unittest.main()

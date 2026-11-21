"""Mekanizma boşluğu (21 Kas): oturum 'sahipte' deyip KAYITLI soru açmadan susar. Tek seferlik dürtme + no_work_close muafiyeti;
reviewer .usage.jsonl yanlış pozitifi; saklama 'held' bildirimi soru değil. Canlı servis/tmux YOK."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review as rv  # noqa: E402
from claudeops import review_store as rs  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops import steward_nowork as snw  # noqa: E402

NOW = 1_800_000_000.0
OWNER = "Bunlar sahipte, sahip kararında."
PROJ = {"p": sw.Project(name="p", phase="planned", cadence_minutes=0)}
CTX = {"open_q": set(), "answer_pending": {}, "review": {}, "jobs": set(), "errors": []}


def view(txt=OWNER, idle_min=90):
    return sw.SessionView(name="p", running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=1.0,
                          last_activity=NOW - idle_min * 60, last_assistant=txt)


def cfg():
    c = sw.Config(enabled=True, mode="act")
    c.claude_idle = "act"
    c.claude_idle_nudge_secs = 3000
    return c


def idle(v, state=None, has_q=False):
    return sw.plan_claude_idle([v], PROJ, state or {}, cfg(), NOW, [], None, open_work=lambda _p: 0,
                               has_question=lambda _p: has_q)


class OwnerClaim(unittest.TestCase):
    def test_nudges_once_when_no_recorded_question(self):
        acts, st = idle(view())
        self.assertEqual([a.kind for a in acts], ["idle_nudge"])
        self.assertEqual(acts[0].payload["via"], "owner_claim_unrecorded")
        self.assertIn("STEWARD-ASK", acts[0].payload["text"])
        acts2, _ = idle(view(idle_min=70), st)      # aynı dönem (oturum dürtmeden beri sessiz): ikinci kez gitmez
        self.assertEqual(acts2, [])

    def test_no_nudge_when_question_recorded_or_short_idle(self):
        self.assertEqual(idle(view(), has_q=True)[0], [])
        self.assertEqual(idle(view(idle_min=55))[0], [])            # 60 dk dolmadı

    def test_no_nudge_without_owner_phrase(self):
        self.assertNotIn("owner_claim_unrecorded", [a.payload.get("via") for a in idle(view(txt="Çalışıyorum."))[0]])

    def test_close_blocked_until_nudged_then_waived(self):
        c = sw.Config(enabled=True, mode="act")
        r = snw.check_session(view(), PROJ["p"], {}, c, NOW, lambda _p: 0, CTX)
        self.assertEqual(r["why"], "no_question")
        # dürtme gitti, oturum ondan SONRA yine boşta ve yine 'sahipte' diyor: no_work_close normal işler
        st = {"owner_claim_nudge": {"p": {"at": NOW - 3000, "session": "p"}}}
        r = snw.check_session(view(idle_min=40), PROJ["p"], st, c, NOW, lambda _p: 0, CTX)
        self.assertNotEqual(r["why"], "no_question", r)
        # kayıtlı soru varsa muafiyet işlemez
        r = snw.check_session(view(idle_min=40), PROJ["p"], st, c, NOW, lambda _p: 0, dict(CTX, open_q={"p"}))
        self.assertEqual(r["why"], "no_question")
        # dürtme ANDAN sonra oturum hiç yanıt vermediyse (last_activity < at) hâlâ engel
        st2 = {"owner_claim_nudge": {"p": {"at": NOW - 60, "session": "p"}}}
        self.assertEqual(snw.check_session(view(), PROJ["p"], st2, c, NOW, lambda _p: 0, CTX)["why"], "no_question")


class UsageScan(unittest.TestCase):
    line = '{"usage": {"prompt_tokens": 5, "completion_tokens": 22185, "cached_tokens": 1022713}, "seconds": 241.9, "cost_usd": 1.2}\n'

    def test_counters_not_secret(self):
        self.assertNotEqual(rv.redact_secrets(self.line), self.line)        # ham tarayıcı yanlış pozitif verir (kök neden)
        self.assertEqual(rs.scan_text("a/x.usage.jsonl", self.line, rv.redact_secrets), self.line)

    def test_real_secret_in_usage_still_held(self):
        bad = self.line + '{"api_key": "sk-ant-abcdefghijklmnopqrstuvwxyz0123456789"}\n'
        self.assertNotEqual(rs.scan_text("a/x.usage.jsonl", bad, rv.redact_secrets), bad)

    def test_md_unchanged(self):
        t = 'token: "abcdefghijklmnop123456"\n'
        self.assertEqual(rs.scan_text("a/x.md", t, rv.redact_secrets), rv.redact_secrets(t))


if __name__ == "__main__":
    unittest.main()

"""TBD#387/1: olumsuz sahip cevabı ("Başlamasın", "devam etme") paused/done projeyi AÇMAZ."""
import unittest

from claudeops import steward as sw

NEGATIVE = (
    "Başlamasın", "başlamasın", "Baslamasin", "başlama", "Başlama.", "başlatma", "başlatmayın", "başlamayın",
    "başlamayalım", "Başlatılmasın", "başlanmasın", "başlamamalı", "başlamıyoruz", "henüz başlamasın",
    "şimdilik başlatmayalım", "2) Başlamasın", "Evet, başlamasın", "ok, başlatma", "Başlama, evet diyene dek",
    "devam etme", "Devam etmesin", "devam etmeyin", "devam etmeyelim", "devam edilmesin", "devam ettirme",
    "bu proje devam etmesin", "start etme", "start verme", "don't start", "Don’t start it yet", "do not start",
    "never restart", "please do not open or start",
)
POSITIVE = (
    "Aç", "evet", "başla", "Başlasın", "başlat", "başlayın", "başlatın", "başlamalı", "devam", "devam et",
    "devam etsin", "devam etmeli", "start", "yes", "ok", "planned", "1) Aç", "Sonnet ile aç",
    "başlamak için aç", "Aç, eski oturuma devam etme", "Başla ama deploy'a devam etme",
    "Sonnet ile aç, eski kuyruğu başlatma",
)


class OpenAnswerNegationTest(unittest.TestCase):
    def test_negated_answers_are_not_open(self):
        for t in NEGATIVE:
            self.assertFalse(sw.is_open_answer(t), t)

    def test_positive_answers_still_open(self):
        for t in POSITIVE:
            self.assertTrue(sw.is_open_answer(t), t)

    def test_plan_tick_does_not_reopen_on_negated_answer(self):
        cfg = sw.Config()
        for phase in ("paused", "done"):
            for text in ("Başlamasın", "devam etme", "start etme"):
                q = sw.Question(id="q1", project="p1", text="soru?", created_at=1000.0, status="answered",
                                answer=text, answered_at=2000.0)
                projects = {"p1": sw.Project(name="p1", phase=phase, cadence_minutes=60)}
                acts, _ = sw.plan_tick([], projects, {}, cfg, 5000.0, [q], [])
                kinds = [a.kind for a in acts if a.kind in ("start", "set_phase", "close_negative_answer")]
                self.assertEqual(kinds, ["close_negative_answer"], (phase, text))


if __name__ == "__main__":
    unittest.main()

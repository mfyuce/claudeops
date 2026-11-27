"""TBD#382 (1): sahibe ait konu (kurulum, harcama, parola, yetki) geçen "bu oturumda mı, devirle mi" sorusu motorca cevaplanmaz.

Çalıştırma: cd py && python3 -m unittest tests.test_steward_tbd382_context"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402

TAIL_TR = " Bu oturumda mı yapayım, yoksa devir notuyla yeni oturuma mı bırakayım?"
TAIL_EN = " Should I do it in this session or hand over to a new session?"

OWNER_TOPICS = [
    "Paket kurulumu gerekiyor." + TAIL_TR,
    "Bağımlılık kurulacak." + TAIL_TR,
    "apt ile kütüphane lazım." + TAIL_TR,
    "sudo isteyen bir adım kaldı." + TAIL_TR,
    "API harcaması 20 USD olacak." + TAIL_TR,
    "Parola girmek gerekiyor." + TAIL_TR,
    "Yetki isteyen bir adım var." + TAIL_TR,
    "API token'ı yenilemek gerekiyor." + TAIL_TR,
    "GitHub token oluşturmam gerekiyor." + TAIL_TR,
    "HF_TOKEN yok, token gir." + TAIL_TR,
    "Bağlam 210K token oldu; ayrıca yeni bir token üretmek gerekiyor." + TAIL_TR,
    "The package install is pending." + TAIL_EN,
    "This will spend about 20 USD." + TAIL_EN,
    "A password is needed." + TAIL_EN,
    "New credentials are needed." + TAIL_EN,
    "The access token has expired." + TAIL_EN,
    "We need 2 tokens for the API." + TAIL_EN,
]

CONTEXT_ONLY = [
    "Bağlam 210K token oldu; bu oturumda mı sürdüreyim, devir notuyla yeni oturuma mı bırakayım?",
    "Adım (2) için ~910K token'lık okuma zincirini bu oturumda mı başlatayım, yoksa devir notuyla yeni oturuma mı bırakayım?",
    "Bağlam 210K/300K token. Bu oturumda mı süreyim, yeni oturuma mı?",
    "Bağlam 180 bin token; bu oturumda mı, devirle mi?",
    "Bağlam (250.000 token) büyüdü: bu oturumda mı sürdüreyim, devirle mi?",
    "Token sayısı yükseldi; bu oturumda mı sürdüreyim, devirle mi?",
    "Bağlam token'ı eşiğe yaklaştı; bu oturumda mı sürdüreyim, devirle mi?",
    "Kalan iş 40K tokens civarı; bu oturumda mı sürdüreyim, devirle mi?",
    "Context is at 200k tokens: continue in this session or hand over to a new session?",
    "We used 250,000 tokens so far. Continue in this session or start a new session?",
    "Token usage is high; continue in this session or do a handover?",
    "Context tokens are at 70%; continue in this session or do a handover?",
    "Context: tokens: 200K. Continue in this session or do a handover?",
]


class OwnerTopicContextQuestionTest(unittest.TestCase):
    def test_owner_topics_are_not_context_questions(self):
        for t in OWNER_TOPICS:
            with self.subTest(t):
                self.assertFalse(sw.is_context_question(t))

    def test_context_measure_still_auto_answered(self):
        for t in CONTEXT_ONLY:
            with self.subTest(t):
                self.assertTrue(sw.is_context_question(t))


class OwnerTopicPlanTickTest(unittest.TestCase):
    Q = "Bu oturumda mı sürdüreyim, yoksa devir notuyla yeni oturuma mı bırakayım?"

    def _plan(self, tokens=100000, **qkw):
        now = 100000.0
        cfg = sw.Config(enabled=True, context_warn_tokens=300000)
        v = sw.SessionView(name="a", running=True, cwd="/tmp/x", cli="claude", busy=False, history_size=100, tmux=True,
                           started_at=1000.0, last_activity=1000.0, context_tokens=tokens, model="claude-sonnet-5-5")
        kw = dict(id="q1", project="a", text=self.Q, created_at=now - 60, source="a")
        kw.update(qkw)
        projects = {"a": sw.Project(name="a", phase="planned", priority=1, cadence_minutes=60)}
        acts, _ = sw.plan_tick([v], projects, {}, cfg, now, [sw.Question(**kw)], [])
        return [a.kind for a in acts if a.name == "a"]

    def test_plain_question_is_answered(self):
        self.assertIn("auto_answer", self._plan())

    def test_owner_topic_in_text_left_open_and_no_handover(self):
        for tokens in (100000, 250000):
            kinds = self._plan(tokens, text="Parola gerekiyor. " + self.Q)
            self.assertNotIn("auto_answer", kinds)
            self.assertNotIn("handover", kinds)

    def test_owner_topic_in_other_fields_left_open(self):
        for kw in ({"options": ["paketi kur (sudo)", "bırak"]}, {"detail": "Durum: API harcaması gerekiyor."},
                   {"extra_texts": ["Parola dosyasını okuyayım mı?"]}, {"prev_texts": ["Yetki vereyim mi?"]}):
            with self.subTest(kw):
                self.assertNotIn("auto_answer", self._plan(**kw))

    def test_context_measure_in_other_fields_is_fine(self):
        self.assertIn("auto_answer", self._plan(detail="Bağlam 210K token."))


if __name__ == "__main__":
    unittest.main()

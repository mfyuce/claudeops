"""`_Tmp` yalıtımı: soru açmak arka planda `claude -p` detay üretimi (`qdetail` thread'i) başlatmaz. 25 Kas oynak testi
(`Directory not empty: 'steward'`) bu thread'in temizlik sırasında geçici dizine `question_detail_cache.json` yazmasıydı;
thread yolu ÇAĞRI anındaki sabitlerden çözdüğü için sonraki bir testin dizinine de yazabiliyordu (`c7d80bf` kapattı)."""
import threading
import unittest
from unittest import mock

from steward_testlib import _Tmp, question_detail, web_steward


class DetailThreadIsolationTest(_Tmp):
    def test_ask_starts_no_detail_generation(self):
        calls = []
        with mock.patch.object(question_detail, "_claude_runner", lambda prompt: calls.append(prompt) or ""), \
                mock.patch.object(web_steward, "notify_phone", lambda *a, **k: True):
            self.assertTrue(web_steward.http_post("/api/steward/ask", {"project": "p", "text": "A mı B mi?"})["ok"])
            for t in threading.enumerate():
                if t.name == "qdetail":
                    t.join(5)
        self.assertEqual(calls, [], "soru açan test arka planda detay üretti: temizlikle yarışır ve gerçek claude çağırır")


if __name__ == "__main__":
    unittest.main()

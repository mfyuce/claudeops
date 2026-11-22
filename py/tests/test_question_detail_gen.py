"""Detaysız sahip sorusu için ucuz modelle otomatik detay: soru başına tek üretim + önbellek + günlük tavan + sessiz düşüş."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claudeops import question_detail as qd
from claudeops import steward as sw


class GenTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="qdg"))
        self.addCleanup(shutil.rmtree, self.d, True)
        self.cache = self.d / "cache.json"
        self.q = sw.Question(id="q1", project="p", text="Hangisi? (R8)", created_at=1.0, options=["a", "b"])

    def gen(self, runner, now=1000.0, cap=3):
        return qd.generate_detail(self.q, runner=runner, cache_path=self.cache, daily_cap=cap, now=now)

    def test_generates_once_and_caches(self):
        calls = []
        r = lambda prompt: calls.append(prompt) or "**Durum** x"
        self.assertEqual(self.gen(r), "**Durum** x")
        self.assertEqual(self.gen(r), "**Durum** x")
        self.assertEqual(len(calls), 1)
        self.assertIn("Hangisi? (R8)", calls[0])

    def test_failure_is_silent_and_not_retried_within_cache(self):
        def boom(prompt):
            raise RuntimeError("x")
        self.assertEqual(self.gen(boom), "")
        r = mock.Mock(return_value="late")
        self.assertEqual(self.gen(r), "")      # başarısız deneme de kayıtlı: tek üretim
        r.assert_not_called()

    def test_daily_cap(self):
        for i in range(3):
            q = sw.Question(id=f"q{i}", project="p", text=f"soru {i}?", created_at=1.0)
            self.assertEqual(qd.generate_detail(q, runner=lambda p: "d", cache_path=self.cache, daily_cap=3, now=1000.0), "d")
        q = sw.Question(id="qx", project="p", text="baska?", created_at=1.0)
        r = mock.Mock(return_value="d")
        self.assertEqual(qd.generate_detail(q, runner=r, cache_path=self.cache, daily_cap=3, now=1000.0), "")
        r.assert_not_called()
        self.assertEqual(qd.generate_detail(q, runner=r, cache_path=self.cache, daily_cap=3, now=1000.0 + 90000), "d")

    def test_model_is_cheap(self):
        self.assertNotIn("opus", qd.MODEL)
        self.assertNotIn("fable", qd.MODEL)

    def test_ensure_detail_saves_on_question(self):
        paths = "qdtest"
        with mock.patch.object(sw, "_pp") as pp:
            pp.return_value = mock.Mock(questions=self.d / "questions.json", sid="qdtest")
            with mock.patch.object(sw, "steward_lock") as lk:
                lk.return_value.__enter__ = lambda s: None
                lk.return_value.__exit__ = lambda *a: False
                sw.save_questions([self.q], paths)
                self.assertTrue(sw.set_question_detail("q1", "DET", paths))
                self.assertFalse(sw.set_question_detail("q1", "OTHER", paths))   # dolu detay ezilmez
                self.assertEqual(sw.load_questions(paths)[0].detail, "DET")


if __name__ == "__main__":
    unittest.main()


class HookTest(unittest.TestCase):
    def test_ensure_async_skips_routine_detailed_answered(self):
        from claudeops.commands import web_steward as ws
        for kw in ({"routine": True}, {"detail": "x"}, {"status": "answered"}):
            q = sw.Question(id="q", project="p", text="s?", created_at=1.0, **kw)
            with mock.patch.object(qd.threading, "Thread") as th:
                qd.ensure_async(q, "default")
                th.assert_not_called()
        q = sw.Question(id="q", project="p", text="s?", created_at=1.0)
        with mock.patch.object(qd.threading, "Thread") as th:
            qd.ensure_async(q, "default")
            th.return_value.start.assert_called_once()

    def test_ws_auto_detail_swallows_errors(self):
        from claudeops.commands import web_steward as ws
        q = sw.Question(id="q", project="p", text="s?", created_at=1.0)
        with mock.patch.object(qd, "ensure_async", side_effect=RuntimeError("x")):
            ws._auto_detail(q, "default")      # istisna sızmaz
        with mock.patch.object(qd, "ensure_async") as ea:
            ws._auto_detail(q, "default")
            ea.assert_called_once()

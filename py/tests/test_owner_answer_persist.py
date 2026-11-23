"""Sahip cevabı HER ZAMAN projenin TOBEDECIDED.md'sine (ilgili TBD maddesinin altına), eylem taşıyorsa TODO.md'ye yazılır."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402


class Pure(unittest.TestCase):
    def test_action_heuristic(self):
        for a in ("evet", "ikisi de", "sıradan git", "sen devam", "A"):
            self.assertFalse(sw.answer_has_action(a), a)
        self.assertTrue(sw.answer_has_action("yuhem menzil adımını atla, açılınca yap"))

    def test_todo_insert_once(self):
        t = sw.todo_insert_answer("- [ ] x\n", "q1", "bunu şöyle yap lütfen", "2026-11-19")
        self.assertIn("- [ ] (sahip cevabı q1, 2026-11-19) bunu şöyle yap lütfen", t)
        self.assertIsNone(sw.todo_insert_answer(t, "q1", "bunu şöyle yap lütfen", "2026-11-19"))


class Http(_Tmp):
    def setUp(self):
        super().setUp()
        from claudeops.commands import web_steward
        self.ws = web_steward
        self.cwd = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.cwd, True)
        open(os.path.join(self.cwd, "TOBEDECIDED.md"), "w").write("- TBD#7 soru\n- TBD#8 baska\n")

    def answer(self, text, by=None):
        q = sw.add_question("p", "TBD#7 hangisi?", source="s", paths=None)
        with mock.patch.object(self.ws, "_cwd_resolver", return_value=lambda n: self.cwd):
            return q, self.ws.http_answer(dict({"id": q.id, "answer": text}, **({"by": by} if by else {})), "default")

    def test_owner_answer_written_under_tbd_and_todo(self):
        q, r = self.answer("yuhem adımını atla, açılınca yap")
        self.assertEqual(r["persisted"], {"tbd": "written", "todo": "written"})
        tbd = open(os.path.join(self.cwd, "TOBEDECIDED.md")).read()
        self.assertLess(tbd.index("TBD#7"), tbd.index(f"[{q.id}]"))
        self.assertLess(tbd.index(f"[{q.id}]"), tbd.index("TBD#8"))
        self.assertIn(f"(sahip cevabı {q.id}", open(os.path.join(self.cwd, "TODO.md")).read())

    def test_short_answer_only_tbd(self):
        _q, r = self.answer("evet")
        self.assertEqual(r["persisted"], {"tbd": "written", "todo": "skipped"})
        self.assertFalse(os.path.exists(os.path.join(self.cwd, "TODO.md")))

    def test_second_answer_same_qid_not_duplicated(self):
        q, _r = self.answer("uzun bir yönerge cevabı burada")
        with mock.patch.object(self.ws, "_cwd_resolver", return_value=lambda n: self.cwd):
            r2 = self.ws.http_answer({"id": q.id, "answer": "uzun bir yönerge cevabı burada"}, "default")
        self.assertEqual(r2["persisted"], {"tbd": "already", "todo": "already"})

    def _brain(self, text):
        q, _ = sw.add_question_ex("p", "TBD#7 x?", source="s", routine=True)
        with mock.patch.object(self.ws, "_cwd_resolver", return_value=lambda n: self.cwd):
            return self.ws.http_answer({"id": q.id, "answer": text, "actor": "brain"}, "default")

    def test_brain_action_answer_persisted(self):          # 23 Kas kayıp önleme: beyin cevabı da yazılır
        r = self._brain("uzun bir yönerge cevabı burada")
        self.assertEqual(r["persisted"], {"tbd": "written", "todo": "written"})

    def test_brain_short_or_nudge_answer_not_persisted(self):
        self.assertNotIn("persisted", self._brain("evet"))
        self.assertNotIn("persisted", self._brain("devam: şu işi bitir ve testleri çalıştır"))


if __name__ == "__main__":
    unittest.main()

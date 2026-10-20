"""Değnekçi yol soyutlaması (çoklu değnekçi P1a): `paths_for`, argümansız = bugünkü davranış, kimlik izolasyonu."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402


def _tree(root):
    """Dizin ağacı: {göreli yol: bayt}."""
    out = {}
    for d, _, files in os.walk(root):
        for fn in files:
            p = os.path.join(d, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = f.read()
    return out


class PathsForTest(_Tmp):
    def test_default_equals_legacy_layout(self):
        p = sw.paths_for("default")
        d = sw.STEWARD_DIR
        self.assertEqual(p, sw.paths_for())
        self.assertEqual((p.root, p.projects, p.ideas, p.questions, p.state, p.log, p.workspace),
                         (d, os.path.join(d, "projects.json"), os.path.join(d, "ideas.json"),
                          os.path.join(d, "questions.json"), os.path.join(d, "state.json"),
                          os.path.join(d, "log.jsonl"), os.path.join(d, "workspace")))
        self.assertEqual((p.daily, p.cards, p.oneshot, p.jobs, p.lock),
                         (os.path.join(d, "daily"), os.path.join(d, "cards"), os.path.join(d, "oneshot"),
                          os.path.join(d, "jobs.json"), os.path.join(d, ".lock")))
        self.assertEqual(sw.card_path("x"), os.path.join(d, "cards", "x.json"))
        self.assertEqual(sw.daily_path("2026-10-20"), os.path.join(d, "daily", "2026-10-20.md"))

    def test_default_follows_constant_patches(self):
        with mock.patch.object(sw, "LOG_JSONL", os.path.join(self.dir.name, "elsewhere.jsonl")):
            self.assertEqual(sw.paths_for().log, os.path.join(self.dir.name, "elsewhere.jsonl"))

    def test_other_sid_under_stewards(self):
        p = sw.paths_for("kitap")
        r = os.path.join(sw.STEWARD_DIR, "stewards", "kitap")
        self.assertEqual((p.root, p.projects, p.log, p.workspace, p.daily, p.lock),
                         (r, os.path.join(r, "projects.json"), os.path.join(r, "log.jsonl"), os.path.join(r, "workspace"),
                          os.path.join(r, "daily"), os.path.join(r, ".lock")))
        self.assertEqual(p.cards, sw.paths_for().cards)   # kartlar ortak

    def test_sid_rejects_traversal(self):
        for bad in ("..", "../x", "a/b", "a.b", "", "Kitap", "k1", "x\n", "/etc", "a\x00b"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                sw.paths_for(bad)

    def _exercise(self, **kw):
        """Tüm depo yazma yollarını gezen sabit senaryo; kw = paths argümanı (ya da hiç)."""
        with mock.patch.object(sw, "_now", return_value=1000.0), \
                mock.patch.object(sw, "_new_id", side_effect=lambda pre: f"{pre}_fixed{next(self._n)}"), \
                mock.patch.object(sw.secrets, "token_hex", return_value="k" * 16), \
                mock.patch.object(sw.time, "strftime", return_value="2026-10-20T10:00:00"):
            sw.upsert_project("kitap", phase="planning", kind="book", goal="g", **kw)
            sw.add_idea("bir fikir", "s", **kw)
            q = sw.add_question("kitap", "A mı B mi?", "s", ["A", "B"], **kw)
            sw.answer_question(q.id, "1", **kw)
            sw.mark_notified(q.id, **kw)
            sw.mark_delivered(q.id, **kw)
            sw.save_state({"summary_date": "2026-10-20"}, **kw)
            sw.save_card("kitap", {"next_step": "n"}, **kw)
            sw.mark_card_stale("kitap", **kw)
            sw.log_event("tick", mode="observe", **kw)
            sw.write_daily("2026-10-20", "özet\n", **kw)
            self.assertEqual(sw.load_projects(**{"paths": kw.get("paths")})["kitap"].phase, "planning")
            self.assertEqual(len(sw.load_questions(kw.get("paths"))), 1)
            self.assertEqual(sw.tail_log(5, kw.get("paths"))[0]["event"], "tick")

    def test_no_arg_matches_explicit_default_byte_for_byte(self):
        import itertools
        self._n = itertools.count()
        self._exercise()
        legacy = _tree(sw.STEWARD_DIR)
        self.assertTrue(legacy)
        self.assertFalse(os.path.exists(os.path.join(sw.STEWARD_DIR, "stewards")))
        import shutil
        shutil.rmtree(sw.STEWARD_DIR)
        self._n = itertools.count()
        self._exercise(paths="default")
        self.assertEqual(_tree(sw.STEWARD_DIR), legacy)
        shutil.rmtree(sw.STEWARD_DIR)
        self._n = itertools.count()
        self._exercise(paths=sw.paths_for("default"))
        self.assertEqual(_tree(sw.STEWARD_DIR), legacy)

    def test_other_sid_isolated_from_default(self):
        sw.upsert_project("kitap", goal="default")
        sw.add_question("kitap", "default sorusu?")
        sw.log_event("a")
        before = _tree(sw.STEWARD_DIR)
        sw.upsert_project("dergi", paths="b", goal="b")
        sw.add_idea("b fikri", paths="b")
        sw.add_question("dergi", "b sorusu?", paths="b")
        sw.save_state({"x": 1}, paths="b")
        sw.log_event("b", paths="b")
        self.assertEqual({k: v for k, v in _tree(sw.STEWARD_DIR).items() if not k.startswith("stewards")}, before)
        self.assertEqual(set(sw.load_projects()), {"kitap"})
        self.assertEqual(set(sw.load_projects("b")), {"dergi"})
        self.assertEqual([q.text for q in sw.load_questions()], ["default sorusu?"])
        self.assertEqual([q.text for q in sw.load_questions("b")], ["b sorusu?"])
        self.assertEqual(sw.load_state(), {})
        self.assertEqual(sw.load_state("b"), {"x": 1})
        self.assertEqual([e["event"] for e in sw.tail_log(9, "b")], ["b"])
        self.assertTrue(os.path.isfile(os.path.join(sw.STEWARD_DIR, "stewards", "b", "projects.json")))


if __name__ == "__main__":
    unittest.main()

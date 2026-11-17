import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402
from steward_testlib import _Tmp  # noqa: E402


class AnsweredByTest(_Tmp):

    def mk(self, **kw):
        q = sw.add_question("p", "hangi model?", source="p-oturum", options=kw.get("options"), paths=None)
        return q

    def test_by_recorded_and_unknown_dropped(self):
        for by, want in (("owner_phone", "owner_phone"), ("brain", "brain"), ("bogus", ""), ("", "")):
            q = self.mk()
            r = sw.answer_question(q.id, "evet", None, by=by)
            self.assertEqual(r.answered_by, want)
            self.assertEqual(r.answer, "evet")

    def test_cops_adds_prefix_once_and_keeps_option_resolution(self):
        q = sw.add_question("p", "hangi?", source="s", options=["A", "B"], paths=None)
        r = sw.answer_question(q.id, "2", None, by="cops")
        self.assertEqual((r.answered_by, r.answer), ("cops", sw.ON_BEHALF_PREFIX + "B"))
        r2 = sw.answer_question(q.id, r.answer, None, by="cops")
        self.assertEqual(r2.answer.count("sahip adına"), 1)

    def test_load_old_record_without_field(self):
        q = self.mk()
        sw.answer_question(q.id, "ok", None)
        self.assertEqual(sw.find_question(q.id, None).answered_by, "")

    def test_cli_default_by_env(self):
        from claudeops.commands import steward as cs
        import argparse
        ns = argparse.Namespace(as_owner=False, on_behalf=False)
        with mock.patch.dict(os.environ, {"COPS_NAME": "cops20261115"}):
            self.assertEqual(cs._answer_by(ns), "cops")
            self.assertEqual(cs._answer_by(argparse.Namespace(as_owner=True, on_behalf=False)), "owner_cli")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COPS_NAME", None)
            self.assertEqual(cs._answer_by(ns), "owner_cli")
            self.assertEqual(cs._answer_by(argparse.Namespace(as_owner=False, on_behalf=True)), "cops")


if __name__ == "__main__":
    unittest.main()


class HttpAnswerByTest(_Tmp):
    def setUp(self):
        super().setUp()
        from claudeops.commands import web_steward
        self.ws = web_steward

    def ask(self):
        return sw.add_question("p", "q?", source="s", paths=None)

    def test_panel_default_cli_by_and_brain(self):
        for data, want in (({}, "owner_panel"), ({"by": "owner_cli"}, "owner_cli"), ({"by": "cops"}, "cops"),
                           ({"by": "brain"}, "owner_panel"), ({"by": "motor"}, "owner_panel"), ({"by": "zzz"}, "owner_panel")):
            q = self.ask()
            r = self.ws.http_answer(dict(data, id=q.id, answer="tamam"), "default")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["question"]["answered_by"], want, data)


class CmdAnswerGuardTest(_Tmp):
    """`steward answer` cevaplanmış soruyu sessizce ezmez; --force ister."""

    def _run(self, qid, ans, force=False):
        import argparse, io
        from contextlib import redirect_stdout
        from claudeops.commands import steward as cs
        a = argparse.Namespace(id=qid, answer=ans, force=force, as_owner=True, on_behalf=False, steward=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cs.cmd_answer(a)
        return rc, buf.getvalue()

    def test_overwrite_refused_without_force(self):
        q = sw.add_question("p", "hangi model?", source="s", paths=None)
        self.assertEqual(self._run(q.id, "birinci")[0], 0)
        rc, out = self._run(q.id, "ikinci")
        self.assertEqual(rc, 1)
        self.assertIn("--force", out)
        self.assertEqual(sw.find_question(q.id, None).answer, "birinci")
        self.assertEqual(self._run(q.id, "ikinci", force=True)[0], 0)
        self.assertEqual(sw.find_question(q.id, None).answer, "ikinci")

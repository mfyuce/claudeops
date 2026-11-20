"""Sahip kuralı 20 Kas: her insan/cops/readlist direktifi hedef projenin TODO.md'sine `- [ ] (tarih, direktif <id>) <özet>`
olarak otomatik yazılır; aynı içerik/aynı id tekrar satır açmaz; beyin ve sistem (restart/review_verify) direktifi yazmaz."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402


class DirectiveAutoTodo(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.todo = os.path.join(self.d, "TODO.md")
        open(self.todo, "w", encoding="utf-8").write("# TODO\n")
        for t, v in (("_cwd_resolver", lambda: (lambda n: self.d)), ("_doc_path", lambda cwd, f: self.todo)):
            p = mock.patch.object(ws, t, v)
            p.start()
            self.addCleanup(p.stop)
        self.p = sw.Project(name="okp", phase="active")

    def rec(self, text, did, **data):
        return ws._todo_record_directive(self.p, "okp", text, did, data)

    def close_all(self):
        b = self.body().replace("- [ ]", "- [x]")
        open(self.todo, "w", encoding="utf-8").write(b)

    def body(self):
        return open(self.todo, encoding="utf-8").read()

    def test_adds_line_with_id_and_flattens_text(self):
        self.assertEqual(self.rec("şunu\nyap", "abc123def456"), "added")
        self.assertRegex(self.body(), r"- \[ \] \(\d{4}-\d\d-\d\d, direktif abc123def456\) şunu yap\n")

    def test_same_content_or_same_id_not_duplicated(self):
        self.rec("şunu yap", "aaaaaaaaaaaa")
        self.assertEqual(self.rec("şunu  yap", "bbbbbbbbbbbb"), "duplicate")
        self.assertEqual(self.rec("başka iş", "aaaaaaaaaaaa"), "duplicate")       # aynı id (kuyruk 2. deneme)
        self.assertEqual(self.body().count("- [ ]"), 1)

    def test_closed_line_allows_same_text_again(self):
        self.rec("şunu yap", "aaaaaaaaaaaa")
        self.close_all()
        self.assertEqual(self.rec("şunu yap", "bbbbbbbbbbbb"), "added")

    def test_brain_and_system_directives_skipped(self):
        self.assertEqual(self.rec("x", "a1", actor="brain"), "skipped:system")
        self.assertEqual(self.rec("x", "a2", reason="restart: y"), "skipped:system")
        self.assertEqual(self.rec("x", "a3", reason="review_verify"), "skipped:system")
        self.assertEqual(self.body(), "# TODO\n")

    def test_remote_or_missing_project_skipped(self):
        self.assertEqual(ws._todo_record_directive(None, "okp", "x", "a4", {}), "skipped:no_local_project")
        self.assertEqual(ws._todo_record_directive(sw.Project(name="r", host="yuhem"), "r", "x", "a5", {}), "skipped:no_local_project")

    def test_state_open_then_closed_then_missing(self):
        self.rec("şunu yap", "aaaaaaaaaaaa")
        with mock.patch.object(ws.sw, "load_projects", lambda sid: {"okp": self.p}):
            self.assertEqual(ws._todo_directive_state("okp", "aaaaaaaaaaaa", "default"), "open")
            self.close_all()
            self.assertEqual(ws._todo_directive_state("okp", "aaaaaaaaaaaa", "default"), "closed")
            self.assertEqual(ws._todo_directive_state("okp", "zzzzzzzzzzzz", "default"), "missing")


if __name__ == "__main__":
    unittest.main()

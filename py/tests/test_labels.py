"""Proje etiketleri: labels.py, `label` CLI, status satırları, değnekçi otomatik kaldırma.
Gerçek `~/.claude/claudeops`a dokunmaz (her test geçici labels.json'a yönlenir)."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from steward_testlib import _Tmp  # noqa: E402
from claudeops import labels, steward as sw  # noqa: E402
from claudeops.commands import label_cmd, web, web_hosts, web_steward as ws  # noqa: E402


class _L(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = mock.patch.object(labels, "_path", lambda: os.path.join(d.name, "labels.json"))
        p.start()
        self.addCleanup(p.stop)


class TestLabels(_L):
    def test_system_defs_present_and_undeletable(self):
        defs = labels.definitions()
        for n in ("stuck", "waiting-owner", "waiting-external", "blocked-budget", "needs-review", "paused-by-owner"):
            self.assertTrue(defs[n]["system"] and defs[n]["desc"])
        self.assertFalse(labels.delete_def("stuck")["ok"])
        self.assertFalse(labels.define("stuck", "#ffffff")["ok"])

    def test_name_validation(self):
        for bad in ("", "Stuck", "-x", "a b", "x" * 33, "ü"):
            self.assertFalse(labels.update("p", [bad])["ok"], bad)
        self.assertTrue(labels.update("p", ["a_b-1"])["ok"])

    def test_add_remove_autodefine_and_find(self):
        self.assertEqual(labels.update("ae", ["stuck", "foo"])["labels"], ["stuck", "foo"])
        self.assertIn("foo", labels.definitions())
        self.assertEqual(labels.find("stuck"), ["ae"])
        self.assertEqual(labels.update("ae", [], ["stuck"])["labels"], ["foo"])
        self.assertEqual(labels.find("stuck"), [])
        self.assertFalse(labels.update("ae", ["zzz"], create_missing=False)["ok"])

    def test_delete_def_strips_assignments(self):
        labels.update("a", ["foo"])
        labels.update("b", ["foo", "stuck"])
        self.assertTrue(labels.delete_def("foo")["ok"])
        self.assertEqual(labels.assignments(), {"b": ["stuck"]})

    def test_key_for_and_attach(self):
        self.assertEqual(labels.key_for("ae20261101"), "ae")
        self.assertEqual(labels.key_for("wifi5gppr"), "wifi5gppr")
        self.assertEqual(labels.key_for("x20261101", "bp"), "bp")
        labels.update("ae", ["stuck"])
        rows = [{"name": "ae20261101", "blueprint": "ae"}, {"name": "zz"}, {"name": "ae"}]
        labels.attach(rows)
        self.assertEqual([r["labels"] for r in rows], [["stuck"], [], ["stuck"]])

    def test_api_action(self):
        self.assertTrue(labels.api_action({"name": "p", "add": ["stuck"]})["ok"])
        self.assertTrue(labels.api_action({"define": {"name": "mine", "color": "#112233", "desc": "d"}})["ok"])
        self.assertEqual(labels.definitions()["mine"]["color"], "#112233")
        self.assertFalse(labels.api_action({"define": {"name": "bad", "color": "red"}})["ok"])
        self.assertFalse(labels.api_action({"delete": "stuck"})["ok"])
        self.assertTrue(labels.api_action({"delete": "mine"})["ok"])
        self.assertFalse(labels.api_action({"name": "p", "add": "stuck"})["ok"])

    def test_corrupt_file_is_empty(self):
        with open(labels._path(), "w") as f:
            f.write("{nope")
        self.assertEqual(labels.assignments(), {})
        self.assertTrue(labels.update("p", ["stuck"])["ok"])

    def test_auto_remove_only_listed(self):
        labels.update("p", ["stuck", "waiting-owner", "needs-review"])
        self.assertEqual(sorted(labels.auto_remove("p")), ["stuck", "waiting-owner"])
        self.assertEqual(labels.labels_of("p"), ["needs-review"])
        self.assertEqual(labels.auto_remove("p"), [])


class TestCli(_L):
    def _run(self, *a):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = label_cmd.run(mock.Mock(find="", args=list(a)))
        return rc, out.getvalue()

    def test_flow(self):
        self.assertEqual(self._run("ae", "+stuck", "+foo")[0], 0)
        self.assertEqual(self._run("ae", "-foo")[1].strip(), "ae: stuck")
        self.assertEqual(self._run("ae20261101")[1].strip(), "stuck")     # tarihli ad blueprint'e çözülür
        self.assertEqual(self._run("ae", "stuck")[0], 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(label_cmd.run(mock.Mock(find="stuck", args=[])), 0)
        self.assertEqual(out.getvalue().strip(), "ae")
        self.assertEqual(self._run("defs", "add", "mine", "#112233", "benim", "etiket")[0], 0)
        self.assertIn("mine", self._run("defs")[1])
        self.assertEqual(self._run("defs", "rm", "stuck")[0], 1)


class TestStewardAutoRemove(_L, _Tmp):
    def setUp(self):
        _L.setUp(self)
        _Tmp.setUp(self)

    def _events(self):
        return [e for e in sw.read_log(paths=None, limit=200)] if hasattr(sw, "read_log") else []

    def test_phase_back_to_planned_removes(self):
        sw.upsert_project("pp", phase="paused")
        labels.update("pp", ["stuck", "paused-by-owner"])
        sw.upsert_project("pp", phase="paused", notes="x")           # girmedi
        self.assertIn("stuck", labels.labels_of("pp"))
        sw.upsert_project("pp", phase="planned")
        self.assertEqual(labels.labels_of("pp"), ["paused-by-owner"])
        with open(sw.LOG_JSONL) as f:
            self.assertIn("label_auto_removed", f.read())

    def test_new_project_in_planned_does_not_touch_labels(self):
        labels.update("qq", ["stuck"])
        sw.upsert_project("qq", phase="planned")
        self.assertEqual(labels.labels_of("qq"), ["stuck"])

    def test_directive_success_removes_but_not_job_delivery(self):
        proj = sw.Project(name="rr", phase="planned")
        labels.update("rr", ["stuck", "waiting-owner"])
        with mock.patch.object(ws, "_give_directive_impl", lambda p, t, **kw: {"ok": True}):
            ws._give_directive(proj, "x", reason="job")
            self.assertEqual(len(labels.labels_of("rr")), 2)
            with mock.patch.object(ws, "_give_directive_impl", lambda p, t, **kw: {"ok": False, "error": "e"}):
                ws._give_directive(proj, "x", reason="answer")
            self.assertEqual(len(labels.labels_of("rr")), 2)
            ws._give_directive(proj, "x", reason="answer")
        self.assertEqual(labels.labels_of("rr"), [])
        with open(sw.LOG_JSONL) as f:
            self.assertIn("label_auto_removed", f.read())



class TestApi(_L):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(web._Handler, "token", "tok")
        p.start()
        self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, body, token="tok"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/labels", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_local_only_route(self):
        self.assertNotIn("/api/labels", web_hosts.HOST_ROUTED_PATHS)

    def test_post_flow_ignores_host_field(self):
        with mock.patch.object(web_hosts, "proxy_action", side_effect=AssertionError("must not proxy")):
            st, body = self.post({"name": "ae", "add": ["stuck"], "host": "ulak_31"})
        self.assertEqual((st, body), (200, {"ok": True, "labels": ["stuck"]}))
        self.assertEqual(labels.assignments(), {"ae": ["stuck"]})
        self.assertEqual(self.post({"delete": "stuck"})[0], 400)           # sistem etiketi silinemez
        self.assertEqual(self.post({"name": "ae", "add": ["BAD"]})[0], 400)
        self.assertEqual(self.post({"name": "ae"}, token="wrong")[0], 401)

    def test_status_payload_has_labels(self):
        labels.update("ae", ["stuck"])
        rows = [{"name": "ae", "blueprint": "ae"}]
        labels.attach(rows)
        self.assertEqual(rows[0]["labels"], ["stuck"])
        self.assertIn("stuck", labels.definitions())


@unittest.skipUnless(shutil.which("node") and os.path.isdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "webui", "node_modules", "typescript")),
                     "node/typescript yok")
class TestSearchParserTs(unittest.TestCase):
    def test_label_terms(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "webui")
        js = r"""const ts=require('typescript'),fs=require('fs');
const out=ts.transpileModule(fs.readFileSync('src/components/shared/searchFilter.ts','utf8'),{compilerOptions:{module:'commonjs'}}).outputText;
const m={exports:{}};new Function('module','exports',out)(m,m.exports);const f=m.exports.matchesSearch;
const it={name:'ae',cwd:'/x',model:'m',cli:'claude',host:'local',labels:['stuck','foo']};
console.log(JSON.stringify([f(it,'label:stuck'),f(it,'label:stuck label:foo ae'),f(it,'label:bar'),f(it,'label:stuck zzz'),f({...it,labels:undefined},'label:stuck'),f(it,'LABEL:Stuck claude'),f(it,'')]));"""
        r = subprocess.run(["node", "-e", js], cwd=root, capture_output=True, text=True, timeout=60)
        self.assertEqual(json.loads(r.stdout), [True, True, False, False, False, True, True], r.stderr)


if __name__ == "__main__":
    unittest.main()

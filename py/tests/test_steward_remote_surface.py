"""Uzak proje yönetimi, A5 (TODO 2026-10-20 (14)): beyin / panel kaynağı / CLI / ntfy tarafında host görünürlüğü.
`http_state` (running + uzak satırlar, soru host'u, `remote_hosts` sağlığı), `http_context`/`http_file`/`_enrich_item`
uzak okuma (term/chat + host-routed files/read, yerel dosya sistemi ASLA), `sw.ask_prefix` `[proje@host]`, `action` log
satırının `host` alanı, `http_job_submit` proje host'u, MCP çıktısı/araç notu, CLI `projects`/`status`, beyin CLAUDE.md notu.

Gerçek ağ/uzak host/spawn YOK: `FakeHost` (test_steward_remote.py'deki desen) + `web_hosts._http_json/_http_raw` ve
`ws.spawn_session` AssertionError'a bağlı; gerçek settings.json sha256'sı modül başında/sonunda karşılaştırılır.

Çalıştırma: python3 -m unittest discover -s py/tests"""
import contextlib
import io
import os
import sys
import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_steward_remote as base  # noqa: E402
from test_steward_remote import HOST, FakeHost, _Remote, _row  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import mcp_queue, mcp_steward, steward as cli, web_steward as ws  # noqa: E402

setUpModule, tearDownModule = base.setUpModule, base.tearDownModule


class SurfaceHost(FakeHost):
    """`FakeHost` + `term/chat` / `files/read` yanıtları; `files/read` çağrıları kaydedilir (`gets`)."""

    def __init__(self):
        super().__init__()
        self.files = {}          # (host, mutlak yol) → metin
        self.exchange = {}       # (host, ad) → (user, assistant)
        self.fail = False        # True: her okuma istisna fırlatır

    def get(self, path, host, query, timeout=None):
        if self.fail:
            self.gets.append((path, host, dict(query)))
            raise OSError("ağ yok")
        if path == "/api/files/read":
            self.gets.append((path, host, dict(query)))
            text = self.files.get((host, query.get("path")))
            return ({"ok": True, "text": text}, 200) if text is not None else ({"ok": False, "error": "not found"}, 404)
        if path == "/api/term/chat" and (host, query.get("name")) in self.exchange:
            self.gets.append((path, host, dict(query)))
            u, a = self.exchange[(host, query.get("name"))]
            return {"ok": True, "supported": True, "user": u, "assistant": a}, 200
        return super().get(path, host, query, timeout)


class _Surface(_Remote):
    def setUp(self):
        super().setUp()
        self.fake_surface = SurfaceHost()
        p = mock.patch.object(ws, "_remote", self.fake_surface)
        p.start()
        self.addCleanup(p.stop)
        self.fake = self.fake_surface
        sw.upsert_project("oiso", phase="planned", host=HOST)
        sw.upsert_project("loc", phase="planned")
        self.settings()
        self.fake.set(HOST, [_row("oiso", cwd="/srv/oiso", model="claude-sonnet-5-5"),
                             _row("degnekci"), _row("zzz")])
        self.local_dir = os.path.join(self.dir.name, "srv-oiso")      # uzak cwd ile AYNI yolda yerel klasör kurulamaz;
        os.makedirs(self.local_dir)                                   # adaş yerel klasör ayrıca denenir
        with open(os.path.join(self.local_dir, "TODO.md"), "w", encoding="utf-8") as f:
            f.write("# YEREL\n")


class TestState(_Surface):
    def test_running_has_remote_rows_with_host_and_project_flag(self):
        self.live = [NS(name="loc", cwd="/l", cli="claude", model="m", pid=1, sid=None, base="loc"),
                     NS(name="oiso", cwd="/yerel/oiso", cli="claude", model="m", pid=2, sid=None, base="oiso")]
        st = ws.http_state()
        names = [(r["name"], r.get("host")) for r in st["running"]]
        self.assertIn(("loc", None), names)                                # yerel öğe: host alanı YOK
        self.assertIn(("oiso", None), names)                               # yerel adaş listede (çalışan süreç) kalır
        self.assertEqual([r for r in st["running"] if r.get("host")],
                         [{"name": "oiso", "cwd": "/srv/oiso", "cli": "claude", "model": "claude-sonnet-5-5", "host": HOST}])
        prj = {p["name"]: p for p in st["projects"]}
        self.assertTrue(prj["oiso"]["running"])
        self.assertEqual(prj["oiso"]["host"], HOST)

    def test_local_namesake_does_not_make_remote_project_running(self):
        self.fake.set(HOST, [_row("oiso", running=False)])
        self.live = [NS(name="oiso", cwd="/yerel/oiso", cli="claude", model="m", pid=2, sid=None, base="oiso")]
        prj = {p["name"]: p for p in ws.http_state()["projects"]}
        self.assertFalse(prj["oiso"]["running"])

    def test_no_double_count(self):
        live = [NS(name="loc", cwd="/l", cli="claude", model="m", pid=1, sid=None, base="loc")]
        remote = [{"name": "oiso", "host": HOST}, {"name": "oiso", "host": HOST}]
        got = ws._running_names_for(live, sw.load_projects(), ws._world(), remote=remote)
        self.assertEqual(got, {"loc", "oiso"})
        self.assertEqual(ws._running_names_for(live, sw.load_projects(), ws._world()), {"loc"})

    def test_stale_host_rows_not_listed(self):
        self.fake.set(HOST, [_row("oiso")], ok=False)
        self.assertEqual([r for r in ws.http_state()["running"] if r.get("host")], [])
        self.assertFalse({p["name"]: p for p in ws.http_state()["projects"]}["oiso"]["running"])

    def test_question_host_and_remote_hosts_health(self):
        sw.add_question("oiso", "uzak soru?")
        sw.add_question("loc", "yerel soru?")
        st = ws.http_state()
        qs = {q["project"]: q for q in st["questions"]}
        self.assertEqual(qs["oiso"].get("host"), HOST)
        self.assertNotIn("host", qs["loc"])
        h = st["remote_hosts"][HOST]
        self.assertEqual((h["state"], h["api"]), ("ok", None))
        self.assertIsNotNone(h["age"])
        self.fake.set(HOST, [], ok=False)
        self.assertEqual(ws.http_state()["remote_hosts"][HOST]["state"], "down")
        ws._HOST_HEALTH[HOST] = {"streak": 3, "until": time.time() + 100, "down": True}
        self.assertEqual(ws.http_state()["remote_hosts"][HOST]["state"], "backoff")
        ws._caps_put(HOST, 0, [], time.time())
        self.assertEqual(ws.http_state()["remote_hosts"][HOST]["api"], 0)

    def test_local_only_state_has_no_remote_keys(self):
        sw.remove_project("oiso")
        self.fake.hosts.clear()
        st = ws.http_state()
        self.assertNotIn("remote_hosts", st)
        self.assertTrue(all("host" not in r for r in st["running"]))


class TestRemoteReads(_Surface):
    def setUp(self):
        super().setUp()
        self.fake.exchange[(HOST, "oiso")] = ("selam", "uzak cevap")
        for d in ("PLAN.md", "TODO.md"):
            self.fake.files[(HOST, "/srv/oiso/" + d)] = f"# uzak {d}\n"

    def local_never(self):
        """Yerel dosya sistemi/git okunursa test patlasın."""
        return [mock.patch.object(ws, "_read_head", lambda *a, **k: (_ for _ in ()).throw(AssertionError("yerel okuma"))),
                mock.patch.object(ws, "_git_short", lambda *a, **k: (_ for _ in ()).throw(AssertionError("yerel git")))]

    def test_context_reads_over_host_not_local_fs(self):
        with contextlib.ExitStack() as st:
            for p in self.local_never():
                st.enter_context(p)
            ctx = ws.http_context("oiso")
        self.assertEqual(ctx["host"], HOST)
        self.assertEqual(ctx["last_exchange"], {"user": "selam", "assistant": "uzak cevap"})
        self.assertEqual(ctx["docs"], {"PLAN.md": "# uzak PLAN.md\n", "TODO.md": "# uzak TODO.md\n"})
        self.assertEqual((ctx["git"], ctx["cwd"], ctx["remote_cwd"], ctx["running"]), (ws.REMOTE_GIT_UNKNOWN, "", "/srv/oiso", True))
        files = [(h, q["name"], q["path"]) for p, h, q in self.fake.gets if p == "/api/files/read"]
        self.assertIn((HOST, "oiso", "/srv/oiso/PLAN.md"), files)
        self.assertEqual(self.fake.posts, [])

    def test_context_running_with_dated_session_name(self):
        """Canlı hata: uzak oturum `oiso20261017`, proje `oiso`; `running` ad eşitliğine bakıyordu, hep False çıkıyordu."""
        self.fake.hosts[HOST]["sessions"][0]["name"] = "oiso20261017"
        self.assertTrue(ws.http_context("oiso")["running"])
        self.assertTrue({p["name"]: p for p in ws.http_state()["projects"]}["oiso"]["running"])
        self.fake.hosts[HOST]["sessions"][0]["name"] = "baska20261017"    # kayıtsız oturum: oiso'ya çözülmemeli
        self.assertFalse(ws.http_context("oiso")["running"])

    def test_same_path_local_folder_is_never_read(self):
        """Uzak cwd'nin AYNI yolunda yerel klasör + TODO.md var: içeriği (YEREL) asla çıkmaz."""
        self.fake.hosts[HOST]["sessions"][0]["cwd"] = self.local_dir
        self.fake.files[(HOST, self.local_dir + "/TODO.md")] = "# UZAK\n"
        ctx = ws.http_context("oiso", docs=True)
        self.assertEqual(ctx["docs"].get("TODO.md"), "# UZAK\n")
        self.assertNotIn("YEREL", repr(ctx))
        self.assertNotIn("YEREL", repr(ws.http_file("oiso", "TODO.md")))

    def test_errors_and_down_host_return_empty_never_raise(self):
        self.fake.fail = True
        ctx = ws.http_context("oiso", docs=True)
        self.assertEqual((ctx["ok"], ctx["last_exchange"], ctx["docs"], ctx["git"]), (True, {}, {}, ws.REMOTE_GIT_UNKNOWN))
        self.assertFalse(ws.http_file("oiso", "TODO.md")["ok"])
        self.fake.fail = False
        self.fake.set(HOST, [_row("oiso")], ok=False)                 # host kapalı: cwd bilinmez, ağ çağrısı yok
        self.fake.gets.clear()
        ctx = ws.http_context("oiso", docs=True)
        self.assertEqual((ctx["docs"], ctx["remote_cwd"]), ({}, ""))
        self.assertFalse(ws.http_file("oiso", "TODO.md")["ok"])
        self.assertEqual([g for g in self.fake.gets if g[0] == "/api/files/read"], [])

    def test_file_read_and_path_guard(self):
        r = ws.http_file("oiso", "PLAN.md")
        self.assertEqual((r["ok"], r["text"], r["truncated"], r["host"]), (True, "# uzak PLAN.md\n", False, HOST))
        r = ws.http_file("oiso", "PLAN.md", max_chars=3)
        self.assertEqual((r["text"], r["truncated"]), ("# u", True))
        for bad in ("../x", "/etc/passwd", ""):
            self.assertFalse(ws.http_file("oiso", bad)["ok"], bad)
        self.assertFalse(ws.http_file("oiso", "YOK.md")["ok"])

    def test_enrich_item_remote(self):
        it = ws._enrich_item({"kind": "stuck", "name": "oiso"}, sw.load_projects(), ws._world())
        self.assertEqual((it["host"], it["last_exchange"]["assistant"]), (HOST, "uzak cevap"))
        self.assertEqual(it["docs"], {"PLAN.md": "# uzak PLAN.md\n", "TODO.md": "# uzak TODO.md\n"})
        self.assertNotIn("YEREL", repr(it))
        loc = ws._enrich_item({"kind": "stuck", "name": "loc"}, sw.load_projects(), ws._world())
        self.assertNotIn("host", loc)


class TestNotifyAndLog(_Surface):
    def test_ask_prefix(self):
        self.assertEqual(sw.ask_prefix("oiso", "default", HOST), "[oiso@ulak31]")
        self.assertEqual(sw.ask_prefix("oiso", "kitap", HOST), "[kitap/oiso@ulak31]")
        self.assertEqual(sw.ask_prefix("oiso"), "[oiso]")
        self.assertEqual(sw.ask_prefix("oiso", "kitap"), "[kitap/oiso]")
        self.assertEqual(sw.ask_prefix("oiso", "default", "local"), "[oiso]")
        self.assertEqual(sw.ask_prefix("", "default", HOST), "[degnekci]")
        q = sw.add_question("oiso", "x?")
        self.assertTrue(sw.question_notification(q, "", "tr", "default", HOST).startswith("[oiso@ulak31] x?"))
        self.assertTrue(sw.question_notification(q, "", "tr").startswith("[oiso] x?"))

    def test_ask_goes_out_with_host_prefix(self):
        sent = []
        with mock.patch.object(ws, "_notify", lambda cfg, text, click="": sent.append(text) or True):
            ws.http_post("/api/steward/ask", {"project": "oiso", "text": "uzak mı?"})
            ws.http_post("/api/steward/ask", {"project": "loc", "text": "yerel mi?"})
        self.assertTrue(sent[0].startswith("[oiso@ulak31] uzak mı?"), sent[0])
        self.assertTrue(sent[1].startswith("[loc] yerel mi?"), sent[1])

    def test_action_log_host_only_remote(self):
        a = sw.Action("handover", "oiso", "dolu", {})
        ws._remember(a, {"ok": True, "host": HOST})
        ws._remember(sw.Action("handover", "loc", "dolu", {}), {"ok": True})
        ws._remember(sw.Action("stop", "loc", "x", {}), {"ok": True, "host": "local"})
        log = {e["name"]: e for e in self.log("action")}
        self.assertEqual(log["oiso"]["host"], HOST)
        self.assertNotIn("host", log["loc"])
        recent = {e["name"]: e for e in ws._ctx().recent}
        self.assertEqual(recent["oiso"]["host"], HOST)
        self.assertNotIn("host", recent["loc"])
        ws._remember(a, {"ok": False, "error": "x"}, host=HOST)       # açık host da yazılır
        self.assertEqual(self.log("action")[-1]["host"], HOST)
        ws._remember_dry(a, host=HOST)
        self.assertEqual(self.log("would:handover")[-1]["host"], HOST)


class TestJobSubmit(_Surface):
    def submit(self, project):
        seen = {}
        with mock.patch.object(ws.sj, "load_services", lambda: {"varaka": {}}), \
                mock.patch.object(ws.sj, "submit_job", lambda *a, **kw: seen.update(kw, args=a) or {"ok": True, "state": "queued"}):
            res = ws.http_post("/api/steward/job/submit", {"project": project, "kind": "import", "service": "varaka"})
        return res, seen

    def test_host_is_the_projects_host(self):
        res, seen = self.submit("oiso")
        self.assertTrue(res["ok"], res)
        self.assertEqual(seen["host"], HOST)
        res, seen = self.submit("loc")
        self.assertEqual(seen["host"], ws.LOCAL_HOST_NAME)

    def test_remote_project_rejects_local_files(self):
        with mock.patch.object(ws.sj, "load_services", lambda: {"varaka": {}}):
            res = ws.http_post("/api/steward/job/submit", {"project": "oiso", "kind": "import", "service": "varaka",
                                                           "files": [os.path.join(self.local_dir, "TODO.md")]})
        self.assertFalse(res["ok"])


class TestMcpAndBrain(_Surface):
    def test_mcp_overview_carries_host_only_for_remote(self):
        self.live = [NS(name="loc", cwd="/l", cli="claude", model="m", pid=1, sid=None, base="loc")]
        with mock.patch.object(mcp_queue, "_api", lambda port, method, path, body=None: ws.http_state()):
            out = mcp_steward._overview(1, {})
        self.assertEqual({r["name"]: r.get("host") for r in out["running"]}, {"loc": None, "oiso": HOST})
        self.assertEqual({p["name"]: p.get("host") for p in out["projects"]}, {"loc": "", "oiso": HOST})

    def test_mcp_signatures_unchanged_notes_added(self):
        by = {t["name"]: t for t in mcp_steward.TOOLS}
        self.assertEqual(set(by["steward_directive"]["inputSchema"]["properties"]),
                         {"name", "text", "model", "effort", "reason", "start_if_stopped"})
        for tool in ("steward_overview", "steward_project_context", "steward_read_file", "steward_directive"):
            self.assertIn("REMOTE host", by[tool]["description"], tool)
            self.assertNotIn("host", by[tool]["inputSchema"]["properties"])
        self.assertEqual(len(mcp_steward.TOOLS), len(mcp_steward.DISPATCH))

    def test_workspace_note_only_when_remote(self):
        plain = sw.build_workspace_claude_md("P", lang="tr")
        self.assertEqual(plain, sw.build_workspace_claude_md("P", lang="tr", remote=False))
        for lang in ("tr", "en"):
            md = sw.build_workspace_claude_md("P", lang=lang, remote=True)
            self.assertGreater(len(md), len(sw.build_workspace_claude_md("P", lang=lang)))
        self.assertIn("host", sw.build_workspace_claude_md("P", lang="en", remote=True))
        path = ws.ensure_workspace(base.settings.steward_config())
        with open(path, encoding="utf-8") as f:
            self.assertIn(sw.REMOTE_NOTE_TR.strip().splitlines()[0], f.read())
        sw.remove_project("oiso")
        path = ws.ensure_workspace(base.settings.steward_config())
        with open(path, encoding="utf-8") as f:
            self.assertNotIn(sw.REMOTE_NOTE_TR.strip().splitlines()[0], f.read())


class TestCli(_Surface):
    def run_cli(self, fn, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(fn(NS(steward=None, sid="default", phase=None, port=1, **kw)), 0)
        return buf.getvalue()

    def test_projects_host_column_only_with_remote(self):
        out = self.run_cli(cli.cmd_projects)
        self.assertIn("HOST", out)
        self.assertRegex(out, rf"oiso\s+planned\s+{HOST}")
        self.assertRegex(out, r"loc\s+planned\s+local")
        sw.remove_project("oiso")
        self.assertNotIn("HOST", self.run_cli(cli.cmd_projects))

    def test_status_remote_summary_and_health(self):
        health = {HOST: {"state": "down", "api": 0, "age": 120}}
        with mock.patch.object(cli, "_api", lambda port, m, path, body=None, sid="default": {"ok": True, "remote_hosts": health}):
            out = self.run_cli(cli.cmd_status)
        self.assertIn(f"oiso@{HOST}", out)
        self.assertIn(f"{HOST}=kapalı (api:0", out)
        health[HOST] = {"state": "ok", "api": 1, "age": None}
        with mock.patch.object(cli, "_api", lambda port, m, path, body=None, sid="default": {"ok": True, "remote_hosts": health}):
            self.assertIn(f"{HOST}=taze (api:1)", self.run_cli(cli.cmd_status))

    def test_status_panel_down_is_unknown_not_error(self):
        with mock.patch.object(cli, "_api", lambda *a, **k: {"ok": False, "error": "cannot reach claudeops panel"}):
            out = self.run_cli(cli.cmd_status)
        self.assertIn("uzak host sağlığı: bilinmiyor", out)

    def test_status_without_remote_does_not_call_panel(self):
        sw.remove_project("oiso")
        with mock.patch.object(cli, "_api", lambda *a, **k: (_ for _ in ()).throw(AssertionError("panel çağrıldı"))):
            out = self.run_cli(cli.cmd_status)
        self.assertNotIn("uzak host", out)


if __name__ == "__main__":
    unittest.main()

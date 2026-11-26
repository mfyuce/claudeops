"""Uzak host'ta AYNI adlı iki ÇALIŞAN oturum = belirsiz hedef (TBD#372): hiçbir uzak eylem gitmez, "satır yok" sanılıp
yeni oturum açılmaz, kapanmış ya da hazır sayılmaz. `_remote_session`/`_remote_running_row` ve çağıranları.

Gerçek ağ/uzak host/tmux/servis YOK: `test_steward_remote_session_resolve` sahte host'u (POST'lar kaydedilir)."""
import dataclasses
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_steward_remote import HOST, _row  # noqa: E402
from test_steward_remote_session_resolve import _Resolve, _facts  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops import window_actions as wa  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.commands import web_review  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

DUP = "adhoc"       # hiçbir projeye çözülmeyen ad: tam ad yolu


class _Dup(_Resolve):
    def setUp(self):
        super().setUp()
        self.rows(DUP, DUP)

    def assert_ambiguous(self, res):
        self.assertEqual((res["ok"], res["code"], res["host"], res["sessions"]),
                         (False, "ambiguous_sessions", HOST, [DUP, DUP]), res)


class TestResolvers(_Dup):
    def test_remote_session_refuses_two_running_rows_of_the_same_name(self):
        fresh, row, err = ws._remote_session(HOST, DUP)
        self.assertEqual((fresh, row), (True, None))
        self.assert_ambiguous(err)
        self.assertEqual([e["sessions"] for e in self.log("remote_ambiguous")], [[DUP, DUP]])

    def test_running_row_is_unknown_not_absent(self):
        self.assertEqual(ws._remote_running_row(HOST, DUP), (False, None))

    def test_one_running_and_one_closed_row_is_not_ambiguous(self):
        self.fake.set(HOST, [_row(DUP, running=False), _row(DUP, busy=True)])
        fresh, row, err = ws._remote_session(HOST, DUP)
        self.assertEqual((fresh, row["busy"], err), (True, True, None))
        self.assertEqual(ws._remote_running_row(HOST, DUP)[1]["busy"], True)

    def test_registered_project_with_duplicate_name_is_refused_too(self):
        self.rows("oiso", "oiso")
        res = self.apply("start")
        self.assertEqual(res["code"], "ambiguous_sessions", res)
        self.assertEqual(ws._remote_running_row(HOST, "oiso"), (False, None))
        self.assertEqual(self.posts(), [])


class TestCallers(_Dup):
    def test_ensure_running_neither_adopts_nor_starts(self):
        self.assert_ambiguous(ws._ensure_running_remote(DUP, HOST, "m", "low", False))
        self.assertEqual(self.posts(), [])

    def test_nudge_handover_and_stop_send_nothing(self):
        cfg, world = ws.steward_config(), ws._world()
        self.assert_ambiguous(ws._remote_nudge(DUP, HOST, sw.Action("nudge", DUP, "t"), cfg, sw.paths_for(cfg.sid),
                                               world, None))
        self.assert_ambiguous(ws._remote_handover(DUP, HOST))
        self.assert_ambiguous(ws._remote_stop(DUP, HOST, world, "default", "engine"))
        self.assert_ambiguous(ws._remote_stop_and_wait(DUP, HOST, world, "default", "engine"))
        self.assertEqual(self.posts(), [])

    def test_waits_do_not_report_ready_or_closed(self):
        self.assertFalse(ws._remote_wait_ready(HOST, DUP, timeout=1))
        self.assertFalse(ws._remote_wait_closed(HOST, DUP, timeout=1))

    def test_panel_stop_with_handover_fails_closed_without_plain_stop_fallback(self):
        calls = []
        with mock.patch.object(web.web_hosts, "proxy_action",
                               lambda *a, **k: (calls.append(a) or ({"ok": True}, 200))), \
                mock.patch.object(web.web_orch, "_fetch_exchange", lambda *a, **k: {"user": "u", "assistant": "a"}), \
                mock.patch.object(web.web_orch, "_wait_for_reply_remote", lambda *a, **k: None):
            res = web._remote_stop_with_handover(HOST, DUP)
        self.assertIsNotNone(res)                   # None = çağıran düz `/api/stop`a düşer
        self.assertEqual((res["ok"], res["code"]), (False, "handover_unreadable"))
        self.assertEqual(calls, [])


class TestReviewDriver(_Resolve):
    def setUp(self):
        super().setUp()
        self.rows("oiso", "rvw_oiso", "rvw_oiso")
        self.drv = ws.RemoteReviewDriver("oiso", HOST)

    def test_start_stop_send_and_sweep_post_nothing(self):
        res = self.drv.start("m", "low")
        self.assertFalse(res["ok"], res)
        self.assertIn("ambiguous_sessions", res["error"])
        self.drv.stop()
        sent = self.drv.send("istem")
        self.assertEqual(sent["ok"], False)
        self.assertIn("ambiguous_sessions", sent["error"])
        self.assertFalse(self.drv.sweep())
        self.assertEqual(self.posts(), [])

    def test_poll_reports_unknown_not_ended(self):
        self.assertEqual(self.drv.poll(), {"running": None, "busy": None, "user": "", "assistant": ""})

    def test_single_review_session_still_gets_stop_and_send(self):
        self.rows("oiso", "rvw_oiso")
        self.assertTrue(self.drv.send("istem")["ok"])
        self.drv.stop()
        self.assertEqual(self.paths_posted(), ["/api/term/input", "/api/stop"])


class TestTwinAppearsDuringHandover(_Resolve):
    """Devir beklemesi uzundur: ikinci adaş sonradan çıkarsa yeniden isteme de `/api/stop` da GİTMEZ."""

    def run_stop(self, replies):
        self.rows(DUP)
        calls = []

        def wait(*a, **k):
            self.rows(DUP, DUP)
            return replies.pop(0)

        with mock.patch.object(web.web_hosts, "proxy_action",
                               lambda path, *a, **k: (calls.append(path) or ({"ok": True}, 200))), \
                mock.patch.object(web.web_orch, "_fetch_exchange", lambda *a, **k: {"user": "u", "assistant": "a"}), \
                mock.patch.object(web.web_orch, "_wait_for_reply_remote", wait):
            res = web._remote_stop_with_handover(HOST, DUP)
        self.assertEqual((res["ok"], res["code"]), (False, "handover_unreadable"), res)
        return calls

    def test_no_second_handover_request(self):
        self.assertEqual(self.run_stop([None, None]), ["/api/handover"])

    def test_no_stop_after_reply(self):
        self.assertEqual(self.run_stop([{"assistant": "READY FOR HANDOVER"}]), ["/api/handover"])


class TestRemoteRefTwins(_Resolve):
    """TBD#380: uzak dosya okuma/yazma hedefi (`_remote_ref`, `_project_cwd_remote`). Aynı adlı iki ÇALIŞAN oturum,
    klasörleri farklı da aynı da olsa belirsizdir: hiçbir uzak okuma/yazma gitmez, hiçbir kayıt kaybolmaz."""

    REAL = "oiso20261017"

    def twins(self, name="oiso", cwds=("/srv/a", "/srv/b")):
        self.fake.set(HOST, [_row(name, cwd=c) for c in cwds])
        self.fake.facts[name] = _facts()

    def variants(self):
        for name in ("oiso", self.REAL):                      # tam ad yolu + proje adından tarihli adaşlar
            for cwds in (("/srv/a", "/srv/b"), ("/srv/a", "/srv/a"), ("", "/srv/b")):
                self.twins(name, cwds)
                self.fake.gets.clear()
                yield name

    def assert_no_io(self):
        self.assertEqual([g[0] for g in self.fake.gets if g[0] in ("/api/files/read", "/api/term/chat")], [])
        self.assertEqual(self.posts(), [])

    def test_remote_ref_refuses(self):
        for _name in self.variants():
            self.assertEqual(ws._remote_ref(HOST, "oiso"), ("", ""))
            self.assertEqual(ws._remote_cwd(HOST, "oiso"), "")

    def test_closed_row_of_the_same_name_does_not_rescue_twins(self):
        self.fake.set(HOST, [_row("oiso", cwd="/srv/a"), _row("oiso", cwd="/srv/b")],
                      closed=[_row("oiso", cwd="/srv/c", running=False)])
        self.assertEqual(ws._remote_ref(HOST, "oiso"), ("", ""))

    def test_tracked_session_twins_are_refused(self):
        state = sw.load_state(sw.paths_for("default"))
        state["owned"] = {"oiso": "asp-fd"}
        sw.save_state(state, sw.paths_for("default"))
        self.fake.set(HOST, [_row("asp-fd", cwd="/srv/a")])
        self.assertEqual(ws._remote_ref(HOST, "oiso", "default"), ("asp-fd", "/srv/a"))
        self.fake.set(HOST, [_row("asp-fd", cwd="/srv/a"), _row("asp-fd", cwd="/srv/b")])
        self.assertEqual(ws._remote_ref(HOST, "oiso", "default"), ("", ""))
        self.assertEqual(ws._remote_edit_doc(HOST, "oiso", "TODO.md", lambda t: t + "x", "default"), "no_folder")
        self.assert_no_io()

    def test_one_running_and_one_closed_row_still_resolves(self):
        self.fake.set(HOST, [_row("oiso", cwd="/srv/a"), _row("oiso", cwd="/srv/b", running=False)])
        self.assertEqual(ws._remote_ref(HOST, "oiso"), ("oiso", "/srv/a"))

    def test_context_and_file_views_read_nothing(self):
        for _name in self.variants():
            rd = ws._remote_read_context(HOST, "oiso", True)
            self.assertEqual(rd, {"last_exchange": {}, "docs": {}, "remote_cwd": ""})
            ctx = ws.http_context("oiso", docs=True)
            self.assertEqual((ctx["last_exchange"], ctx["docs"], ctx["remote_cwd"]), ({}, {}, ""))
            res = ws.http_file("oiso", "TODO.md")
            self.assertFalse(res["ok"], res)
            self.assert_no_io()

    def test_card_is_not_read_or_overwritten(self):
        sw.save_card("oiso", {"name": "oiso", "summary": "eski", "source_hash": "h", "updated_at": 1.0})
        before = sw.load_card("oiso")
        for _name in self.variants():
            self.assertIsNone(ws._remote_raw_card(HOST, "oiso", 5.0))
            self.assertFalse(ws.refresh_card("oiso", ws.steward_config())["ok"])
            self.assertEqual(ws._refresh_remote_cards(ws.steward_config(), [sw.load_projects()["oiso"]], {}, 1.0, 1, 5.0), [])
            self.assertEqual(sw.load_card("oiso"), before)
            self.assert_no_io()

    def test_advance_todo_status_is_unknown(self):
        seen = []
        cfg = dataclasses.replace(ws.steward_config(), advance_findings=True)
        with mock.patch.object(ws.sa, "candidates", lambda data, cwd_of, remote_of, todo_of: [todo_of("oiso", "f1")]):
            for _name in self.variants():
                seen.append(ws._advance_candidates(cfg))
                self.assert_no_io()
        self.assertEqual(seen, [[""]] * 6)

    def test_idea_export_writes_nothing_and_keeps_the_idea(self):
        idea = sw.add_idea("yeni fikir", source="t", project="oiso")
        for _name in self.variants():
            res = ws.http_idea_export({"id": idea.id, "kind": "todo", "target": "project"})
            self.assertEqual((res["ok"], res["skipped"], res["remote"]), (False, ["oiso"], {"oiso": "no_folder"}), res)
            self.assertIn(idea.id, [i.id for i in sw.load_ideas()])
            self.assert_no_io()

    def test_owner_answer_stays_queued_for_retry(self):
        q = sw.add_question("oiso", "hangisi?", source="oiso")
        q = sw.answer_question(q.id, "ikinciyi uygula")
        for _name in self.variants():
            res = ws._persist_owner_answer(q, "default")
            self.assertEqual((res["tbd"], res.get("retry")), ("no_folder", "queued"), res)
            self.assertIn(q.id, sw.load_state()["persist_retry"])
            self.assert_no_io()

    def test_directive_reports_the_unwritten_todo_line(self):
        for _name in self.variants():
            res = self.directive("oiso")
            self.assertEqual((res["ok"], res["code"], res["todo"]), (False, "ambiguous_sessions", "error"), res)
            self.assert_no_io()

    def test_review_driver_has_no_folder_and_keeps_findings(self):
        drv = ws.RemoteReviewDriver("oiso", HOST)
        paths = sw.paths_for("default")
        web_review.rv.save_findings(paths, {"f1": {"project": "oiso", "state": "approved", "severity": "P1",
                                                   "title": "`yok_ad` bozuk", "where": "a.py:1", "body": "b"}})
        for _name in self.variants():
            ok, msg = drv.ready()
            self.assertFalse(ok, msg)
            with self.assertRaises(RuntimeError):
                drv.cwd()
            self.assertFalse(drv.start("m", "low")["ok"])
            self.assertIsNone(drv.read_rel("a.py"))
            self.assertFalse(drv.export_file("TODO.md", lambda t: (t + "x", ["f1"]))["ok"])
            with mock.patch.object(web_review, "ownership", lambda: {"hosts": {"oiso": HOST}}):
                self.assertFalse(web_review._export_remote(ws.steward_config(), "oiso", "TODO.md", 1.0, "")["ok"])
            self.assertEqual(web_review.rv.load_findings(paths)["f1"]["state"], "approved")
            self.assert_no_io()

    def test_review_cwd_fallback_refuses_dated_twins(self):
        self.fake.set(HOST, [_row(self.REAL, cwd="/srv/a"), _row(self.REAL, cwd="/srv/b")])
        drv = ws.RemoteReviewDriver("oiso", HOST)
        self.assertEqual(drv._project_cwd_remote(drv._rows()), "")
        self.fake.set(HOST, [_row(self.REAL, cwd="/srv/a")])
        self.assertEqual(drv._project_cwd_remote(drv._rows()), "/srv/a")


class TestMirrorWindowTwins(unittest.TestCase):
    """TBD#380: masaüstü yansı penceresi (`web._open_mirror_window`) aynı adlı iki ÇALIŞAN uzak satırda açılmaz."""

    def open(self, rows, **kw):
        spawned, focused = [], []
        mirrors = {"yuhem:s1": [1]} if kw.pop("open", False) else {}
        with mock.patch.object(web, "get_host", lambda h: {"name": h}), \
                mock.patch.object(web.web_hosts, "get_cached", lambda h: {"sessions": rows}), \
                mock.patch.object(web, "detect_display", lambda: ":1"), \
                mock.patch.object(web, "_x11_display_ok", lambda d: True), \
                mock.patch.object(web.mirrors, "running_mirrors", lambda: mirrors), \
                mock.patch.object(web.mirrors, "focus_window", lambda *a: focused.append(a) or True), \
                mock.patch.object(web, "open_mirror_window", lambda *a, **k: spawned.append(a) or True):
            return web._open_mirror_window("s1", "yuhem", 8765, lang="en", **kw), spawned, focused

    def row(self, cwd="/srv/a", **kw):
        return _row("s1", cwd=cwd, **kw)

    def test_twins_are_refused_whatever_their_folder_or_tmux_state(self):
        for rows in ([self.row(), self.row("/srv/b")], [self.row(), self.row()], [self.row(), self.row(tmux=False)]):
            for kw in ({}, {"force": True}, {"open": True}, {"require_running": False, "focus": False}):
                res, spawned, focused = self.open(rows, **kw)
                self.assertFalse(res["ok"], (rows, kw, res))
                self.assertIn("more than one running session", res["error"])
                self.assertIn("yuhem:s1, yuhem:s1", res["error"])
                self.assertEqual((spawned, focused), ([], []))

    def test_a_stopped_row_of_the_same_name_does_not_hide_the_running_one(self):
        res, spawned, _ = self.open([self.row(running=False), self.row("/srv/b")])
        self.assertEqual((res["ok"], len(spawned)), (True, 1), res)


class TestRemoteRefRowChoice(_Resolve):
    """TBD#390/1: `_remote_ref` calisan satiri secer; yalniz kapali adaslarin klasoru farkliysa tahmin etmez."""

    def test_running_row_wins_over_an_earlier_stopped_one(self):
        self.fake.set(HOST, [_row("oiso", cwd="/srv/eski", running=False), _row("oiso", cwd="/srv/yeni")])
        self.assertEqual(ws._remote_ref(HOST, "oiso"), ("oiso", "/srv/yeni"))

    def test_running_row_without_folder_does_not_borrow_a_stopped_one(self):
        self.fake.set(HOST, [_row("oiso", cwd="")], closed=[_row("oiso", cwd="/srv/eski", running=False)])
        self.assertEqual(ws._remote_ref(HOST, "oiso"), ("", ""))

    def test_stopped_twins_with_different_folders_are_refused(self):
        self.fake.set(HOST, [], closed=[_row("oiso", cwd="/srv/a", running=False), _row("oiso", cwd="/srv/b", running=False)])
        self.assertEqual(ws._remote_ref(HOST, "oiso"), ("", ""))

    def test_stopped_twins_with_one_folder_resolve(self):
        self.fake.set(HOST, [], closed=[_row("oiso", cwd="/srv/a", running=False), _row("oiso", cwd="/srv/a", running=False)])
        self.assertEqual(ws._remote_ref(HOST, "oiso"), ("oiso", "/srv/a"))

    def test_tracked_session_follows_the_same_rule(self):
        state = sw.load_state(sw.paths_for("default"))
        state["owned"] = {"oiso": "asp-fd"}
        sw.save_state(state, sw.paths_for("default"))
        self.fake.set(HOST, [_row("asp-fd", cwd="/srv/eski", running=False), _row("asp-fd", cwd="/srv/yeni")])
        self.assertEqual(ws._remote_ref(HOST, "oiso", "default"), ("asp-fd", "/srv/yeni"))
        self.fake.set(HOST, [], closed=[_row("asp-fd", cwd="/srv/a", running=False), _row("asp-fd", cwd="/srv/b", running=False)])
        self.assertEqual(ws._remote_ref(HOST, "oiso", "default"), ("", ""))


if __name__ == "__main__":
    unittest.main()

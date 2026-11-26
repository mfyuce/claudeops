"""Uzak host'ta AYNI adlı iki ÇALIŞAN oturum = belirsiz hedef (TBD#372): hiçbir uzak eylem gitmez, "satır yok" sanılıp
yeni oturum açılmaz, kapanmış ya da hazır sayılmaz. `_remote_session`/`_remote_running_row` ve çağıranları.

Gerçek ağ/uzak host/tmux/servis YOK: `test_steward_remote_session_resolve` sahte host'u (POST'lar kaydedilir)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_steward_remote import HOST, _row  # noqa: E402
from test_steward_remote_session_resolve import _Resolve  # noqa: E402
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()


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

"""Panel 'devir + kapat' (force'suz /api/stop) HER oturumda devir alır, READY FOR HANDOVER görünce kapatır (stdlib unittest, mock).

Hata: `human_stop_with_ho` proje olmayan / değnekçi kapalı-observe / beyin / uzak oturum için None dönüyor, çağıran sessizce düz
`_stop`a düşüyordu: düğme adı yalandı. Beklenen: devir mesajı -> READY -> kapat; devir alınamazsa/zaman aşımında KAPATMAZ,
hata + `suggest:"force"` döner (arayüz 'kapat'ı önerir). force/exact davranışı değişmez. Canlı oturum/tmux/ağ YOK."""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


def _sess(name="x1", pid=11, cli="claude"):
    return NS(name=name, pid=pid, cli=cli, cwd="/w", sid="s1")


def setUpModule():
    """Gerçek ~/.claude/claudeops/diag.log'a YAZMA (canlı logda sahte ho_stop_timeout kayıtları oluşmuştu)."""
    global _DIAG
    _DIAG = mock.patch.object(web, "diag_log", lambda *a, **k: None)
    _DIAG.start()


def tearDownModule():
    _DIAG.stop()


class _Prov:
    def __init__(self, conv=True, base=None):
        self.conv, self.base = conv, base if base is not None else {"user": "u", "assistant": "a"}

    def has_conversation(self):
        return self.conv

    def last_exchange(self, cwd, sid):
        return self.base

    def snapshot_for_live_sid(self, cwd):
        return None


class LocalTest(unittest.TestCase):
    def run_local(self, kind="exact", procs=None, prov=None, tmux=True, ho=None, reply="READY FOR HANDOVER x"):
        procs = [_sess()] if procs is None else procs
        calls = []
        with mock.patch.object(web, "_find_running_for_action", lambda n: (kind, procs)), \
                mock.patch.object(web, "get_provider", lambda cli: prov or _Prov()), \
                mock.patch.object(web, "is_tmux_backed", lambda pid: tmux), \
                mock.patch.object(web, "_handover", lambda n, lang="tr", exact=False, extra="": (calls.append(("ho", exact)) or (ho or {"ok": True}))), \
                mock.patch.object(web.turns, "wait_for_reply", lambda *a, **k: (calls.append(("wait", k["require_marker"])) or reply)), \
                mock.patch.object(web, "_stop", lambda n, lang="tr", exact=False: (calls.append(("stop", n, exact)) or {"ok": True, "result": ["clean"]})):
            return web._stop_with_handover("x1"), calls

    def test_success_handover_then_exact_stop(self):
        res, calls = self.run_local()
        self.assertEqual(res, {"ok": True, "result": ["clean"], "handover": True})
        self.assertEqual(calls, [("ho", True), ("wait", "READY FOR HANDOVER"), ("stop", "x1", True)])

    def test_handover_send_failure_does_not_stop(self):
        res, calls = self.run_local(ho={"ok": False, "error": "boom"})
        self.assertFalse(res["ok"])
        self.assertEqual((res["code"], res["suggest"]), ("handover_failed", "force"))
        self.assertNotIn("stop", [c[0] for c in calls])

    def test_timeout_does_not_stop(self):
        res, calls = self.run_local(reply=None)
        self.assertEqual((res["ok"], res["code"], res["suggest"]), (False, "handover_timeout", "force"))
        self.assertNotIn("stop", [c[0] for c in calls])

    def test_unreadable_baseline_does_not_handover_or_stop(self):
        prov = _Prov(); prov.base = None
        with mock.patch.object(web, "_find_running_for_action", lambda n: ("exact", [_sess()])), \
                mock.patch.object(web, "get_provider", lambda cli: prov), \
                mock.patch.object(web, "is_tmux_backed", lambda pid: True), \
                mock.patch.object(web, "_handover", side_effect=AssertionError("devir gönderilmemeli")), \
                mock.patch.object(web, "_stop", side_effect=AssertionError("kapatılmamalı")):
            r = web._stop_with_handover("x1")
        self.assertEqual(r["code"], "handover_unreadable")

    def test_not_applicable_returns_none(self):
        self.assertIsNone(self.run_local(kind="none", procs=[])[0])
        self.assertIsNone(self.run_local(kind="ambiguous", procs=[_sess(), _sess(pid=2)])[0])
        self.assertIsNone(self.run_local(prov=_Prov(conv=False))[0])      # shell: devredilecek konuşma yok
        self.assertIsNone(self.run_local(tmux=False)[0])

    def test_english_message(self):
        with mock.patch.object(web, "_find_running_for_action", lambda n: ("exact", [_sess()])), \
                mock.patch.object(web, "get_provider", lambda cli: _Prov()), \
                mock.patch.object(web, "is_tmux_backed", lambda pid: True), \
                mock.patch.object(web, "_handover", lambda *a, **k: {"ok": False, "error": "x"}):
            r = web._stop_with_handover("x1", lang="en")
        self.assertIn("NOT closed", r["error"])


class ReaskTest(unittest.TestCase):
    """READY gelmezse devir BİR kez yeniden istenir; ikinci bekleme de boşsa kapatmaz; süre üst sınırı 900 sn."""
    def run_it(self, replies):
        calls, seq = [], list(replies)
        with mock.patch.object(web, "_find_running_for_action", lambda n: ("exact", [_sess()])), \
                mock.patch.object(web, "get_provider", lambda cli: _Prov()), \
                mock.patch.object(web, "is_tmux_backed", lambda pid: True), \
                mock.patch.object(web, "_handover", lambda n, lang="tr", exact=False, extra="": (calls.append("ho") or {"ok": True})), \
                mock.patch.object(web.turns, "wait_for_reply", lambda *a, **k: (calls.append(("wait", k["timeout"])) or seq.pop(0))), \
                mock.patch.object(web, "_stop", lambda n, lang="tr", exact=False: (calls.append("stop") or {"ok": True})):
            return web._stop_with_handover("x1"), calls

    def test_reask_then_ready(self):
        out, calls = self.run_it([None, "READY FOR HANDOVER"])
        self.assertTrue(out["ok"])
        self.assertEqual(calls.count("ho"), 2)
        self.assertIn("stop", calls)
        self.assertEqual(web.HO_STOP_TIMEOUT_SECONDS, 900.0)

    def test_reask_still_none_does_not_close(self):
        out, calls = self.run_it([None, None])
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "handover_timeout")
        self.assertNotIn("stop", calls)


class RemoteTest(unittest.TestCase):
    def run_remote(self, row=True, prov=None, baseline=True, ho=None, reply="READY FOR HANDOVER", force_stop=None):
        calls = []

        def proxy(path, host, body, timeout=None):
            calls.append((path, dict(body)))
            if path == "/api/handover":
                return (ho or {"ok": True}), 200
            return (force_stop or {"ok": True, "result": ["clean"]}), 200
        with mock.patch.object(web.web_steward, "_remote_running_row", lambda h, n: (True, {"name": n, "cli": "claude"} if row else None)), \
                mock.patch.object(web, "get_provider", lambda cli: prov or _Prov()), \
                mock.patch.object(web.web_orch, "_fetch_exchange", lambda *a, **k: {"user": "u", "assistant": "a"} if baseline else None), \
                mock.patch.object(web.web_hosts, "proxy_action", proxy), \
                mock.patch.object(web.web_orch, "_wait_for_reply_remote", lambda *a, **k: (calls.append(("wait", k["require_marker"])) or reply)):
            return web._remote_stop_with_handover("ulak31", "oiso1"), calls

    def test_success_handover_then_forced_exact_stop(self):
        res, calls = self.run_remote()
        self.assertTrue(res["ok"] and res["handover"])
        self.assertEqual([c[0] for c in calls], ["/api/handover", "wait", "/api/stop"])
        stop_body = calls[-1][1]
        self.assertEqual((stop_body["force"], stop_body["exact"]), (True, True))      # devir ALINDI: uzak taraf ikinci devir yapmaz

    def test_timeout_does_not_stop(self):
        res, calls = self.run_remote(reply=None)
        self.assertEqual((res["ok"], res["code"], res["suggest"]), (False, "handover_timeout", "force"))
        self.assertNotIn("/api/stop", [c[0] for c in calls])

    def test_handover_failure_does_not_stop(self):
        res, calls = self.run_remote(ho={"ok": False, "error": "unreachable"})
        self.assertEqual(res["code"], "handover_failed")
        self.assertEqual([c[0] for c in calls], ["/api/handover"])

    def test_unreadable_baseline_does_nothing(self):
        res, calls = self.run_remote(baseline=False)
        self.assertEqual(res["code"], "handover_unreadable")
        self.assertEqual(calls, [])

    def test_not_applicable_returns_none(self):
        self.assertIsNone(self.run_remote(row=False)[0])
        self.assertIsNone(self.run_remote(prov=_Prov(conv=False))[0])


class RouteTest(unittest.TestCase):
    """Gerçek HTTP: yeni yol YALNIZ açık `ho:true` ile (BulkBar `stop`); alan yoksa /api/stop ESKİ davranışla birebir
    (OptionsRow restart/reset, window_actions, cops kill hâlâ devir BEKLEMEZ). ho:true arka plan işi: hemen {ok,pending}."""

    def setUp(self):
        self.calls = []
        self.local_ho = None            # `_stop_with_handover` dönüşü (None = uygulanamaz)
        self.release = threading.Event()   # iş parçacığını test denetler

        def rec(tag, ret):
            def f(*a, **k):
                self.calls.append((tag, a, k))
                return ret() if callable(ret) else ret
            return f

        def ho_local(*a, **k):
            self.calls.append(("ho_local", a, k))
            self.release.wait(5)
            return self.local_ho
        web._HO_STOP_JOBS.clear()
        for p in (
            mock.patch.object(web.web_steward, "human_stop_with_ho", rec("human", None)),
            mock.patch.object(web, "_stop_with_handover", ho_local),
            mock.patch.object(web, "_remote_stop_with_handover", rec("ho_remote", {"ok": True, "handover": True})),
            mock.patch.object(web, "_stop", rec("stop", {"ok": True, "result": []})),
            mock.patch.object(web.web_hosts, "proxy_action", lambda path, host, body, timeout=None: (self.calls.append(("proxy", (path, host, dict(body)), {})) or ({"ok": True}, 200))),
            mock.patch.object(web._Handler, "token", "tok"),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(web._HO_STOP_JOBS.clear)
        self.addCleanup(self.release.set)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def req(self, method, path, body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                   data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Authorization": "Bearer tok", "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())

    def post(self, body):
        return self.req("POST", "/api/stop", body)

    def status(self, name="a", host="local"):
        return self.req("GET", f"/api/stop/status?name={name}&host={host}")

    def wait_state(self, name="a", host="local"):
        for _ in range(100):
            st = self.status(name, host)
            if st["state"] != "pending":
                return st
            threading.Event().wait(0.05)
        self.fail("iş bitmedi")

    def tags(self):
        return [c[0] for c in self.calls]

    # -- eski davranış (ho alanı YOK): devir bekleme YOK ------------------------------------------------------------
    def test_without_ho_field_old_behaviour_byte_for_byte(self):
        r = self.post({"name": "a"})
        self.assertEqual(r, {"ok": True, "result": []})
        self.assertEqual(self.tags(), ["human", "stop"])             # ne devir yardımcısı ne iş parçacığı
        self.assertEqual(web._HO_STOP_JOBS, {})

    def test_force_with_ho_is_a_400_conflict_never_a_silent_plain_stop(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post({"name": "a", "force": True, "ho": True})
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(self.tags(), [])                            # hiçbir şey kapatılmadı
        self.assertEqual(web._HO_STOP_JOBS, {})

    def test_exact_with_ho_still_hands_over_with_the_exact_flag(self):
        """Canlı hata (danisppr): `exact:true` + `ho:true` düz durdurmaya düşüp devirsiz kapattı."""
        self.local_ho = {"ok": True, "result": [], "handover": True}
        r = self.post({"name": "a", "exact": True, "ho": True})
        self.assertEqual((r["ok"], r["pending"]), (True, True))
        self.release.set()
        self.assertEqual(self.wait_state()["state"], "ok")
        self.assertIn("ho_local", self.tags())
        self.assertNotIn("human", self.tags())                        # proje çözen yol exact'ta atlanır
        ho_call = next(c for c in self.calls if c[0] == "ho_local")
        self.assertTrue(ho_call[2].get("exact"))

    def test_exact_with_ho_not_applicable_falls_back_to_exact_plain_stop(self):
        self.local_ho = None
        self.post({"name": "a", "exact": True, "ho": True})
        self.release.set()
        self.wait_state()
        stop_call = next(c for c in self.calls if c[0] == "stop")
        self.assertTrue(stop_call[2].get("exact"))

    def test_exact_without_ho_stays_plain_stop(self):
        self.post({"name": "a", "exact": True})
        self.assertEqual(self.tags(), ["stop"])

    def test_remote_without_ho_goes_straight_to_proxy(self):
        self.post({"name": "a", "host": "ulak31"})
        self.assertEqual(self.tags(), ["proxy"])
        self.assertNotIn("force", self.calls[0][1][2])               # uzak çağrı değişmedi

    # -- ho:true: arka plan işi ------------------------------------------------------------------------------------
    def test_ho_returns_pending_immediately_while_job_blocks(self):
        r = self.post({"name": "a", "ho": True})                     # iş `release` bekliyor: istek yine de HEMEN döner
        self.assertEqual((r["ok"], r["pending"]), (True, True))
        self.assertEqual(self.status()["state"], "pending")
        self.assertNotIn("stop", self.tags())

    def test_ho_failure_is_reported_and_never_plain_stops(self):
        self.local_ho = {"ok": False, "code": "handover_timeout", "suggest": "force", "error": "x"}
        self.post({"name": "a", "ho": True})
        self.release.set()
        st = self.wait_state()
        self.assertEqual((st["state"], st["result"]["code"], st["result"]["suggest"]), ("error", "handover_timeout", "force"))
        self.assertNotIn("stop", self.tags())

    def test_ho_success(self):
        self.local_ho = {"ok": True, "result": ["clean"], "handover": True}
        self.post({"name": "a", "ho": True})
        self.release.set()
        st = self.wait_state()
        self.assertEqual((st["state"], st["result"]["handover"]), ("ok", True))

    def test_ho_not_applicable_falls_back_to_plain_stop_inside_the_job(self):
        self.local_ho = None
        self.post({"name": "a", "ho": True})
        self.release.set()
        self.assertEqual(self.wait_state()["state"], "ok")
        self.assertEqual(self.tags(), ["human", "ho_local", "stop"])

    def test_second_ho_while_pending_does_not_start_second_job(self):
        self.post({"name": "a", "ho": True})
        r = self.post({"name": "a", "ho": True})
        self.assertTrue(r.get("already"))
        self.release.set()
        self.wait_state()
        self.assertEqual(self.tags().count("ho_local"), 1)

    def test_remote_ho_runs_remote_helper_in_job(self):
        self.post({"name": "a", "host": "ulak31", "ho": True})
        st = self.wait_state(host="ulak31")
        self.assertEqual(st["state"], "ok")
        self.assertEqual(self.tags(), ["ho_remote"])

    def test_job_exception_becomes_error_with_force_hint(self):
        with mock.patch.object(web, "_stop_with_handover", side_effect=RuntimeError("kaboom")):
            self.post({"name": "a", "ho": True})
            st = self.wait_state()
        self.assertEqual((st["state"], st["result"]["suggest"]), ("error", "force"))

    def test_status_unknown_after_restart_is_none(self):
        self.assertEqual(self.status("never"), {"ok": True, "state": "none"})


if __name__ == "__main__":
    unittest.main()

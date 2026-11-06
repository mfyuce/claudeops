"""Panel 'devir + kapat' (force'suz /api/stop) HER oturumda devir alır, READY FOR HANDOVER görünce kapatır (stdlib unittest, mock).

Hata: `human_stop_with_ho` proje olmayan / değnekçi kapalı-observe / beyin / uzak oturum için None dönüyor, çağıran sessizce düz
`_stop`a düşüyordu: düğme adı yalandı. Beklenen: devir mesajı -> READY -> kapat; devir alınamazsa/zaman aşımında KAPATMAZ,
hata + `suggest:"force"` döner (arayüz 'kapat'ı önerir). force/exact davranışı değişmez. Canlı oturum/tmux/ağ YOK."""
import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


def _sess(name="x1", pid=11, cli="claude"):
    return NS(name=name, pid=pid, cli=cli, cwd="/w", sid="s1")


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
    """Gerçek HTTP: /api/stop force'suz yol devir yardımcılarına gider; force/exact ESKİ yolu aynen korur."""

    def setUp(self):
        self.calls = []
        self.local_ho = None            # `_stop_with_handover` dönüşü (None = uygulanamaz)

        def rec(tag, ret):
            def f(*a, **k):
                self.calls.append((tag, a, k))
                return ret() if callable(ret) else ret
            return f
        for p in (
            mock.patch.object(web.web_steward, "human_stop_with_ho", rec("human", None)),
            mock.patch.object(web, "_stop_with_handover", lambda *a, **k: (self.calls.append(("ho_local", a, k)) or self.local_ho)),
            mock.patch.object(web, "_remote_stop_with_handover", rec("ho_remote", {"ok": True, "handover": True})),
            mock.patch.object(web, "_stop", rec("stop", {"ok": True, "result": []})),
            mock.patch.object(web.web_hosts, "proxy_action", lambda path, host, body, timeout=None: (self.calls.append(("proxy", (path, host, dict(body)), {})) or ({"ok": True}, 200))),
            mock.patch.object(web._Handler, "token", "tok"),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/stop", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": "Bearer tok", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def tags(self):
        return [c[0] for c in self.calls]

    def test_local_plain_uses_handover_and_never_plain_stop(self):
        self.local_ho = {"ok": False, "code": "handover_timeout", "suggest": "force", "error": "x"}
        r = self.post({"name": "a"})
        self.assertEqual(r["code"], "handover_timeout")
        self.assertEqual(self.tags(), ["human", "ho_local"])        # düz _stop'a DÜŞMEZ

    def test_local_falls_back_to_plain_stop_when_handover_not_applicable(self):
        self.post({"name": "a"})
        self.assertEqual(self.tags(), ["human", "ho_local", "stop"])

    def test_local_force_skips_handover(self):
        self.post({"name": "a", "force": True})
        self.assertEqual(self.tags(), ["stop"])

    def test_local_exact_skips_handover(self):
        self.post({"name": "a", "exact": True})
        self.assertEqual(self.tags(), ["stop"])

    def test_remote_plain_uses_remote_handover_not_proxy(self):
        r = self.post({"name": "a", "host": "ulak31"})
        self.assertTrue(r["handover"])
        self.assertEqual(self.tags(), ["ho_remote"])

    def test_remote_force_goes_straight_to_proxy(self):
        self.post({"name": "a", "host": "ulak31", "force": True})
        self.assertEqual(self.tags(), ["proxy"])
        self.assertTrue(self.calls[0][1][2]["force"])


if __name__ == "__main__":
    unittest.main()

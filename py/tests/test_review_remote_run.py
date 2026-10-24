"""Uzak review koşusu (TBD#117 ek 3 c): RemoteReviewProc durum makinesi ve RemoteReviewDriver kapıları/çağrı sırası.
Gerçek uzak host/ağ YOK; sürücü ve `_remote_*` yardımcıları sahte."""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import review_remote_run as rrun  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402

PROMPT = "ÖNEMLİ istem metni: projeyi incele ve raporla"
REPORT = "## R-1 | P2 | a.py:1 | x\ngövde"
OK = lambda t: "## R-" in t or "BULGU YOK" in t  # noqa: E731


class Drv:
    def __init__(self, script, start_ok=True):
        self.script, self.start_ok, self.calls = list(script), start_ok, []

    def start(self, model, effort):
        self.calls.append("start")
        return {"ok": self.start_ok, "error": "" if self.start_ok else "x"}

    def send(self, text):
        self.calls.append("send")
        return {"ok": True}

    def poll(self):
        self.calls.append("poll")
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]

    def stop(self):
        self.calls.append("stop")


def idle(user="", asst=""):
    return {"running": True, "busy": False, "user": user, "assistant": asst}


def proc(drv, clock=None, min_wait=0.0):
    t = [0.0]

    def tick():
        t[0] += 1.0
        return t[0]
    return rrun.RemoteReviewProc(drv, "m", "low", PROMPT, OK, sleep=lambda s: None, clock=clock or tick,
                                 poll_seconds=0.0, min_wait=min_wait)


class ProcTest(unittest.TestCase):
    def test_done_needs_two_stable_idle_polls_and_stops_session(self):
        d = Drv([idle(), idle(PROMPT, "yarım"), idle(PROMPT, REPORT), idle(PROMPT, REPORT)])
        out, err = proc(d).communicate(timeout=1000)
        self.assertEqual((out, err), (REPORT, ""))
        self.assertEqual(d.calls[-1], "stop")

    def test_stale_answer_from_previous_conversation_is_not_taken(self):
        old = idle("eski soru", REPORT)
        d = Drv([old, old])
        with self.assertRaises(subprocess.TimeoutExpired):          # eski cevap bizimki sayılmaz, bitmez
            proc(d).communicate(timeout=20)

    def test_busy_never_finishes_then_timeout_then_abort_returns_partial(self):
        d = Drv([idle(), {"running": True, "busy": True, "user": PROMPT, "assistant": "## R-1 | P3 | b:1 | kısmi"}])
        p = proc(d)
        with self.assertRaises(subprocess.TimeoutExpired):
            p.communicate(timeout=15)
        p.wait(timeout=5)                                           # _terminate yolu: uzak oturumu kapatır
        out, err = p.communicate()
        self.assertIn("kısmi", out)
        self.assertEqual(d.calls.count("stop"), 1)
        self.assertNotEqual(p.returncode, 0)

    def test_session_died_without_report_is_failure(self):
        d = Drv([idle(), {"running": False, "busy": None, "user": "", "assistant": ""}])
        out, err = proc(d).communicate(timeout=1000)
        self.assertEqual(out, "")
        self.assertIn("ended", err)

    def test_start_failure_and_cancel(self):
        out, err = proc(Drv([idle()], start_ok=False)).communicate(timeout=10)
        self.assertEqual(out, "")
        self.assertIn("remote start", err)
        p = proc(Drv([idle(), idle(PROMPT, "")]))
        p.abort()                                                    # cancel_key -> _killpg -> abort
        out, err = p.communicate()
        self.assertEqual(err, "aborted")

    def test_report_without_format_is_not_done(self):
        txt = "Üzgünüm, bir hata oluştu."
        p = proc(Drv([idle(), idle(PROMPT, txt), idle(PROMPT, txt)]))
        out, err = p.communicate(timeout=1000)
        self.assertEqual(out, txt)
        self.assertEqual(p.returncode, 2)
        self.assertIn("format", err)


class DriverTest(unittest.TestCase):
    def setUp(self):
        self.posts = []
        self.rows = [{"name": "far", "cwd": "/srv/far", "running": True, "busy": False}]

        def post(host, path, body, timeout, rt=None):
            self.posts.append((path, dict(body)))
            return {"ok": True}
        for p in (mock.patch.object(ws, "_remote_post", post),
                  mock.patch.object(ws, "_remote_rows", lambda host, rt=None: self.rows),
                  mock.patch.object(ws, "_remote_denied", lambda *a, **k: self.denied),
                  mock.patch.object(ws, "_remote_sleep", lambda s: None),
                  mock.patch.object(ws.web_review, "remote_projects", lambda idx=None: {"far": ("default", object())}),
                  mock.patch.object(ws.sw, "log_event", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        self.denied = None
        self.running_after_start = True

        def running_row(host, name, rt=None):
            if any(pa == "/api/start" for pa, _ in self.posts) and self.running_after_start:
                return True, {"name": name, "running": True, "busy": False}
            return True, None
        p = mock.patch.object(ws, "_remote_running_row", running_row)
        p.start()
        self.addCleanup(p.stop)
        self.drv = ws.RemoteReviewDriver("far", "ulak_31")

    def test_gate_denial_blocks_start_and_reports_why(self):
        self.denied = {"ok": False, "error": "target denied: remote actions are disabled", "code": "remote_disabled"}
        self.assertEqual(self.drv.ready(), (False, "target denied: remote actions are disabled"))
        res = self.drv.start("m", "low")
        self.assertFalse(res["ok"])
        self.assertEqual(self.posts, [])

    def test_start_registers_distinct_session_then_starts_read_only_fresh_ucli(self):
        res = self.drv.start("deepseek-v4.1-flash", "high")
        self.assertTrue(res["ok"], res)
        self.assertEqual([p for p, _ in self.posts], ["/api/register", "/api/start"])
        reg, st = self.posts[0][1], self.posts[1][1]
        self.assertEqual((reg["name"], reg["cwd"], reg["cli"]), ("rvw_far", "/srv/far", "ucli"))
        self.assertEqual((st["name"], st["fresh"], st["cli"], st["permission_mode"], st["effort"]),
                         ("rvw_far", True, "ucli", "read-only", "high"))
        self.assertFalse(ws.sw.valid_name("") or "rvw_far".startswith("far"))     # proje adıyla BAŞLAMAZ: ad hoc, değnekçi dokunmaz

    def test_leftover_review_session_is_stopped_first_and_registration_skipped(self):
        self.rows.append({"name": "rvw_far", "running": True, "busy": False, "cwd": "/srv/far"})
        state = {"closed": False}

        def closed(host, name, timeout=0):
            state["closed"] = True
            return True
        with mock.patch.object(ws, "_remote_wait_closed", closed):
            res = self.drv.start("m", "medium")
        self.assertTrue(res["ok"], res)
        self.assertEqual([p for p, _ in self.posts], ["/api/stop", "/api/start"])
        self.assertTrue(state["closed"])
        self.assertTrue(self.posts[0][1]["exact"])

    def test_send_goes_exact_to_review_session_only(self):
        self.assertTrue(self.drv.send("istem\nikinci satır\n## R-1 | P2 | x")["ok"])
        path, body = self.posts[0]
        self.assertEqual((path, body["name"], body["exact"]), ("/api/term/input", "rvw_far", True))
        self.assertNotIn("\n", body["text"])                                   # REPL satırı ayrı tur sayar: TEK satır
        self.assertTrue(body["text"].startswith("istem ikinci satır ## R-1 | P2 | x"))

    def test_ready_fails_when_remote_folder_unknown(self):
        self.rows[:] = [{"name": "baska", "cwd": "/x", "running": True}]
        ok, msg = self.drv.ready()
        self.assertFalse(ok)
        self.assertIn("unknown", msg)


if __name__ == "__main__":
    unittest.main()

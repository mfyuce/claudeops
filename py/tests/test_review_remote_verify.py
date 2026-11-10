"""Uzak (host'lu) projenin bulguları O HOST'taki proje oturumuna doğrulatılır: aç -> sor -> sohbetten oku -> kendi açtığını kapat.
Ağ YOK: `io=` sahte. Çalıştırma: python3 -m unittest discover -s py/tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from test_review_findings_flow import _Flow  # noqa: E402
from claudeops import review as rv  # noqa: E402
from claudeops.commands import web_review as wr, web_steward as ws  # noqa: E402


class FakeIO:
    def __init__(self, running=None, busy=False, answer=None):
        self.running = dict(running or {})        # ad -> busy
        if busy:
            self.running = {k: True for k in self.running}
        self.answer = answer                      # fn(text) -> asistan cevabı
        self.calls, self.last = [], ""

    def sessions(self, host):
        return [{"name": n, "running": True, "busy": b, "host": host} for n, b in self.running.items()]

    def start(self, host, name):
        self.calls.append(("start", host, name))
        self.running[name] = False
        return {"ok": True}

    def send(self, host, name, text):
        self.calls.append(("send", host, name))
        self.last = self.answer(text) if self.answer else ""
        return {"ok": True}

    def last_assistant(self, host, name):
        return self.last

    def stop(self, host, name):
        self.calls.append(("stop", host, name))
        self.running.pop(name, None)
        return {"ok": True}


def answer_all(verdict):
    def f(text):
        ids = [ln.split(" | ")[0][2:] for ln in text.splitlines() if ln.startswith("- ") and " | " in ln]
        return "baktım\n" + "\n".join(f"{rv.VERDICT_MARK} {i} {verdict} gerekçe" for i in ids)
    return f


class RemoteVerifyTest(_Flow):
    def setUp(self):
        super().setUp()
        from claudeops import settings
        settings.save_settings({"stewards": {"rev": {"enabled": "on", "mode": "act", "role": "reviewer"}}})
        self.cfg = ws.steward_config("rev")
        self.clock = [1_900_000_000.0]

    def now(self):
        return self.clock[0]

    def sleep(self, s):
        self.clock[0] += s

    def run_verify(self, io):
        rows = wr.verify_candidates(self.cfg, "a")
        return rows, wr.remote_verify(self.cfg, "a", "ulak_31", rows, io=io, now=self.now, sleep=self.sleep,
                                      background=False)

    def test_opens_asks_applies_and_closes_own_session(self):
        self.seed()
        io = FakeIO(answer=answer_all("verified"))
        rows, res = self.run_verify(io)
        self.assertTrue(res["ok"], res)
        self.assertEqual([self.findings()[r["id"]]["state"] for r in rows], ["verified"] * len(rows))
        self.assertEqual([c[0] for c in io.calls], ["start", "send", "stop"])
        self.assertEqual(io.calls[0][1:], ("ulak_31", "a"))

    def test_running_session_is_used_and_left_open(self):
        self.seed()
        io = FakeIO(running={"a20261021": False}, answer=answer_all("refuted"))
        rows, res = self.run_verify(io)
        self.assertTrue(res["ok"], res)
        self.assertEqual([c[0] for c in io.calls], ["send"])        # açmadı, kapatmadı
        self.assertEqual(io.calls[0][2], "a20261021")
        self.assertEqual({self.findings()[r["id"]]["state"] for r in rows}, {"refuted"})

    def test_busy_session_not_disturbed(self):
        self.seed()
        io = FakeIO(running={"a": True}, answer=answer_all("verified"))
        _rows, res = self.run_verify(io)
        self.assertEqual(res.get("code"), "session_busy")
        self.assertEqual(io.calls, [])
        self.assertEqual({v["state"] for v in self.findings().values()}, {"new"})

    def test_ambiguous_sessions_refused(self):
        self.seed()
        io = FakeIO(running={"a": False, "a_2": False})
        _rows, res = self.run_verify(io)
        self.assertEqual(res.get("code"), "ambiguous_sessions")
        self.assertEqual(io.calls, [])

    def test_no_answer_returns_to_new_and_closes(self):
        self.seed()
        io = FakeIO(answer=lambda t: "düşünüyorum")
        rows, res = self.run_verify(io)
        self.assertTrue(res["ok"])
        self.assertEqual({self.findings()[r["id"]]["state"] for r in rows}, {"new"})
        self.assertEqual(io.calls[-1][0], "stop")

    def test_process_verdicts_skips_remote_findings(self):
        self.seed()
        rows = wr.verify_candidates(self.cfg, "a")
        p = wr.sw.paths_for("rev")
        rv.mark_verify_sent(p, [r["id"] for r in rows], wr.REMOTE_VERIFY_SESSION, "", self.now())
        old = wr._VERDICT_READER
        wr._VERDICT_READER = lambda proj: ("a", "\n".join(f"{rv.VERDICT_MARK} {r['id']} verified x" for r in rows))
        try:
            self.assertEqual(wr.process_verdicts(self.cfg), [])
        finally:
            wr._VERDICT_READER = old


if __name__ == "__main__":
    unittest.main()

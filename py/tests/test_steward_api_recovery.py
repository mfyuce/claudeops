"""API hatası dayanıklılığı (saf mantık): sahte transkript metni + sahte saat. Tek oturum: 1/3/10 dk 'devam', en çok 3, sonra bırak+bildir;
birden çok oturum aynı anda = kesinti: tek bildirim, 10 dk'da tek yoklama, düzelince 4'lü gruplarla uyandırma."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw  # noqa: E402

ERR = "API Error: 500 {\"type\":\"error\",\"error\":{\"type\":\"api_error\",\"message\":\"Internal server error\"}}"
T0 = 100000.0


def view(name, text=ERR, **kw):
    base = dict(running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=1.0, last_activity=T0 - 600,
                last_assistant=text)
    base.update(kw)
    return sw.SessionView(name=name, **base)


def run(views, st_err, st_out, now, skip=()):
    return sw.plan_api_recovery(views, lambda v: True, set(skip), st_err, st_out, now)


class KindTest(unittest.TestCase):
    def test_classification(self):
        k = sw.api_error_kind
        self.assertEqual(k(ERR), "retry")
        self.assertEqual(k("API Error: 429 rate limited"), "retry")
        self.assertEqual(k("API Error: Overloaded"), "retry")
        self.assertEqual(k("API Error: Connection lost mid-response. The response above may be incomplete."), "retry")
        self.assertEqual(k("API Error: Request timed out"), "retry")
        self.assertEqual(k("API Error: 400 invalid_request_error prompt is too long"), "fatal")
        self.assertEqual(k("API Error: 401 authentication_error"), "fatal")
        self.assertEqual(k("normal bir cevap: API Error: 500 üzerine konuştuk"), "")
        self.assertEqual(k(""), "")
        # kimlik içindeki 3 haneli sayı 5xx sanılmaz
        self.assertEqual(k("API Error: 400 request_id req_5xx1 id 503abc"), "fatal")


class SingleSessionTest(unittest.TestCase):
    def test_backoff_nudges_then_giveup(self):
        v = [view("cli")]
        acts, e, o = run(v, {}, {}, T0)
        self.assertEqual((acts, o), ([], {}))                                  # yeni görüldü: bekle
        acts, e, o = run(v, e, o, T0 + 30)
        self.assertEqual(acts, [])
        acts, e, o = run(v, e, o, T0 + 61)
        self.assertEqual([(a.kind, a.name, a.payload["text"], a.payload["n"]) for a in acts], [("nudge", "cli", "devam", 1)])
        acts, e, o = run(v, e, o, T0 + 61 + 100)
        self.assertEqual(acts, [])                                             # 2. için 3 dk bekle
        acts, e, o = run(v, e, o, T0 + 61 + 181)
        self.assertEqual([a.payload["n"] for a in acts], [2])
        acts, e, o = run(v, e, o, T0 + 61 + 181 + 601)
        self.assertEqual([a.payload["n"] for a in acts], [3])
        acts, e, o = run(v, e, o, T0 + 61 + 181 + 601 + 300)
        self.assertEqual(acts, [])
        t_end = T0 + 61 + 181 + 601 + 601
        acts, e, o = run(v, e, o, t_end)
        self.assertEqual([(a.kind, a.name) for a in acts], [("api_giveup", "cli")])
        acts, e, o = run(v, e, o, t_end + 5000)
        self.assertEqual(acts, [])                                             # döngü yok: bir kez bırakılır ve bildirilir

    def test_recovery_clears_state_and_new_error_resets(self):
        acts, e, o = run([view("cli")], {}, {}, T0)
        acts, e, o = run([view("cli", text="tamamdır, devam ediyorum")], e, o, T0 + 10)
        self.assertEqual((acts, e, o), ([], {}, {}))
        acts, e, o = run([view("cli", text="API Error: 529 Overloaded")], {}, {}, T0 + 20)
        self.assertEqual(e["cli"]["nudges"], 0)

    def test_untouched_when_busy_subagent_recent_activity_fatal_or_skipped(self):
        for kw in ({"busy": True}, {"subagent_active": True}, {"subagent_unknown": True}, {"last_activity": T0 - 5},
                   {"text": "API Error: 400 invalid_request_error"}, {"running": False}):
            acts, e, o = run([view("cli", **kw)], {}, {}, T0)
            self.assertEqual((acts, e), ([], {}), kw)
        acts, e, o = run([view("cli")], {}, {}, T0, skip=["cli"])
        self.assertEqual((acts, e), ([], {}))
        acts, e, o = sw.plan_api_recovery([view("cli")], lambda v: False, set(), {}, {}, T0)
        self.assertEqual((acts, e), ([], {}))                                   # yönetilmeyen oturum


class OutageTest(unittest.TestCase):
    def test_outage_single_notice_probe_then_grouped_wake(self):
        names = [f"s{i}" for i in range(6)]
        v = [view(n) for n in names]
        acts, e, o = run(v, {}, {}, T0)
        kinds = [(a.kind, a.name) for a in acts]
        self.assertEqual(kinds[0], ("api_outage", ""))
        self.assertEqual(sorted(acts[0].payload["names"]), names)
        nudges = [a for a in acts if a.kind == "nudge"]
        self.assertEqual([a.name for a in nudges], ["s0"])                      # TEK yoklama oturumu
        acts, e, o = run(v, e, o, T0 + 120)
        self.assertEqual(acts, [])                                              # bildirim/yoklama tekrarlanmaz
        acts, e, o = run(v, e, o, T0 + 601)
        self.assertEqual([(a.kind, a.name) for a in acts], [("nudge", "s0")])   # 10 dk'da bir tek yoklama (s0 hâlâ takılı)
        # s0 ilerledi: düzelme -> kalanlar 4'lü gruplarla
        v2 = [view("s0", text="ilerledim")] + [view(n) for n in names[1:]]
        acts, e, o = run(v2, e, o, T0 + 700)
        self.assertEqual(acts[0].kind, "api_recovered")
        woke = [a.name for a in acts if a.kind == "nudge"]
        self.assertEqual(woke, ["s1", "s2", "s3", "s4"])
        acts, e, o = run(v2, e, o, T0 + 760)
        self.assertEqual([a.name for a in acts if a.kind == "nudge"], ["s5"])
        acts, e, o = run(v2, e, o, T0 + 820)
        self.assertEqual(acts, [])                                              # herkes bir kez uyandırıldı
        acts, e, o = run([view(n, text="tamam") for n in names], e, o, T0 + 900)
        self.assertEqual((acts, e, o), ([], {}, {}))                            # kesinti kaydı düşer

    def test_two_sessions_is_an_outage_one_is_not(self):
        acts, e, o = run([view("a"), view("b")], {}, {}, T0)
        self.assertEqual(acts[0].kind, "api_outage")
        acts, e, o = run([view("a")], {}, {}, T0)
        self.assertEqual((acts, o), ([], {}))


class PlanTickIntegrationTest(unittest.TestCase):
    def test_state_keys_absent_when_clean_and_present_when_stuck(self):
        proj = {"p1": sw.Project(name="p1", phase="planned")}
        cfg = sw.Config(enabled=True)
        _, st = sw.plan_tick([view("p1", text="selam")], proj, {}, cfg, T0, [], [])
        self.assertNotIn("api_err", st)
        self.assertNotIn("api_outage", st)
        _, st = sw.plan_tick([view("p1")], proj, {}, cfg, T0, [], [])
        self.assertIn("p1", st["api_err"])
        acts, st = sw.plan_tick([view("p1")], proj, st, cfg, T0 + 70, [], [])
        self.assertEqual([a.kind for a in acts if a.kind == "nudge"], ["nudge"])

    def test_observe_mode_does_not_apply_nudge(self):
        a = sw.Action("nudge", "p1", "x", {"text": "devam", "n": 1})
        apply, dry, _ = sw.observe_filter([a], "observe", {}, T0)
        self.assertEqual(([x.kind for x in apply], [x.kind for x in dry]), ([], ["nudge"]))
        apply, dry, _ = sw.observe_filter([a], "act", {}, T0)
        self.assertEqual([x.kind for x in apply], ["nudge"])


class ApplyTest(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        from claudeops.commands import web_steward as ws
        self.ws, self.mock = ws, mock
        self.cfg = sw.Config(enabled=True)
        self.proj = {"cli": sw.Project(name="cli", phase="planned")}
        self.addCleanup(mock.patch.stopall)

    def test_nudge_sends_devam_to_tmux_session(self):
        ws, mock = self.ws, self.mock
        sess = mock.Mock(pid=1, cli="claude")
        sess.name = "cli"
        with mock.patch.object(ws, "_running", return_value=sess), mock.patch.object(ws, "is_tmux_backed", return_value=True), \
                mock.patch.object(ws, "_send", return_value=True) as send, mock.patch.object(ws.sw, "log_event"):
            res = ws._apply(sw.Action("nudge", "cli", "x", {"text": "devam", "n": 1}), self.cfg, self.proj)
        self.assertTrue(res["ok"])
        send.assert_called_once_with("cli", "claude", "devam")

    def test_nudge_refused_when_not_tmux_or_not_running(self):
        ws, mock = self.ws, self.mock
        with mock.patch.object(ws, "_running", return_value=None), mock.patch.object(ws.sw, "log_event"):
            self.assertFalse(ws._apply(sw.Action("nudge", "cli", "x", {}), self.cfg, self.proj)["ok"])
        sess = mock.Mock(pid=1, cli="claude")
        with mock.patch.object(ws, "_running", return_value=sess), mock.patch.object(ws, "is_tmux_backed", return_value=False), \
                mock.patch.object(ws, "_send") as send:
            self.assertFalse(ws._apply(sw.Action("nudge", "cli", "x", {}), self.cfg, self.proj)["ok"])
        send.assert_not_called()

    def test_giveup_and_outage_only_notify(self):
        ws, mock = self.ws, self.mock
        with mock.patch.object(ws, "_notify", return_value=True) as n, mock.patch.object(ws, "_send") as send, \
                mock.patch.object(ws.sw, "log_event"):
            for a in (sw.Action("api_giveup", "cli", "x", {}), sw.Action("api_outage", "", "x", {"names": ["a", "b"]}),
                      sw.Action("api_recovered", "a", "x", {})):
                self.assertTrue(ws._apply(a, self.cfg, self.proj)["ok"])
        self.assertEqual(n.call_count, 3)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()

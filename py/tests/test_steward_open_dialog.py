"""Soru diyaloğu açık (ya da sahip yeni cevap veriyor) oturum devir süresi dolunca kapatılmaz, diyaloğa mesaj yazılmaz
(27 Kas: devir açık AskUserQuestion'a yazıldı, 15 dk sonra oturum sahiple konuşmanın ortasında yeniden açıldı). Disk/ağ YOK."""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import steward as sw, steward_keepwarm as kw, steward_nowork as snw  # noqa: E402
from claudeops.owner_dialog import owner_dialog_state  # noqa: E402
from claudeops.commands import web, web_steward as ws  # noqa: E402

NOW = 1_800_000_000.0


def _ts(sec):
    import datetime
    return datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _a(mid, tool="AskUserQuestion", tid="t1", at=NOW, **kw):
    return json.dumps(dict({"type": "assistant", "timestamp": _ts(at), "message": {"id": mid, "content": [
        {"type": "tool_use", "id": tid, "name": tool, "input": {}}]}}, **kw))


def _res(tid="t1", at=NOW, error=False):
    return json.dumps({"type": "user", "timestamp": _ts(at), "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": "x", "is_error": error}]}})


def _say(text="evet", at=NOW, kind="human", **kw):
    return json.dumps(dict({"type": "user", "timestamp": _ts(at), "origin": {"kind": kind},
                            "message": {"content": text}}, **kw))


class Transcript(unittest.TestCase):
    def test_unanswered_question_is_open(self):
        self.assertEqual(owner_dialog_state([_a("m1")]), (True, 0.0))
        self.assertEqual(owner_dialog_state([_a("m1", tool="ExitPlanMode")])[0], True)
        self.assertEqual(owner_dialog_state([_a("m1", tool="Bash")]), (False, 0.0))
        # aynı iletinin ikinci aracı diyaloğu kapatmaz
        self.assertTrue(owner_dialog_state([_a("m1"), _a("m1", tool="Bash", tid="t2")])[0])

    def test_answer_or_dismissal_closes_and_is_owner_input(self):
        for error in (False, True):
            self.assertEqual(owner_dialog_state([_a("m1"), _res(at=NOW + 60, error=error)]), (False, NOW + 60))

    def test_later_turn_or_typed_prompt_closes_an_orphan(self):
        self.assertFalse(owner_dialog_state([_a("m1"), _a("m2", tool="Bash", tid="t2")])[0])
        self.assertEqual(owner_dialog_state([_a("m1"), _say(at=NOW + 5)]), (False, NOW + 5))

    def test_noise_is_not_owner_input(self):
        lines = [_a("m1"), _say("<task-notification>x</task-notification>", kind="task-notification", at=NOW + 9),
                 _say(at=NOW + 9, isMeta=True), _say(at=NOW + 9, isSidechain=True), "bozuk", "{}"]
        self.assertEqual(owner_dialog_state(lines), (True, 0.0))
        self.assertEqual(owner_dialog_state([_a("m1", isSidechain=True)]), (False, 0.0))


def _view(**kw):
    base = dict(running=True, cwd="/w", cli="claude", busy=False, tmux=True, started_at=NOW - 9000, last_activity=NOW - 4000)
    base.update(kw)
    return sw.SessionView(name="a", **base)


class Plan(unittest.TestCase):
    def setUp(self):
        self.projects = {"a": sw.Project(name="a", phase="planned", cadence_minutes=0)}
        self.cfg = sw.Config(enabled=True, mode="act", ho_grace_minutes=15, context_warn_tokens=1000)

    def tick(self, v, st=None, now=NOW, **cfg):
        for k, val in cfg.items():
            setattr(self.cfg, k, val)
        acts, st = sw.plan_tick([v], self.projects, st or {}, self.cfg, now, [], [])
        return [a for a in acts if a.name == "a"], st

    def test_threshold_handover_is_never_typed_into_a_dialog(self):
        for defer_max in (30, 0):
            acts, st = self.tick(_view(question_open=True, context_tokens=900000), handover_defer_max_minutes=defer_max)
            self.assertEqual([(a.kind, a.reason) for a in acts], [("handover_deferred", "question_open")])
            self.assertNotIn("a", st.get("ho_pending", {}))

    def test_expired_grace_waits_while_dialog_open_and_records_once(self):
        st = {"ho_pending": {"a": NOW - 3600}}
        for text in ("", "## READY FOR HANDOVER"):
            acts, st2 = self.tick(_view(question_open=True, last_assistant=text, busy=None), st)
            self.assertEqual([(a.kind, a.reason) for a in acts], [("handover_deferred", "question_open")])
            self.assertEqual(st2["ho_pending"]["a"], NOW - 3600)
        acts, st3 = self.tick(_view(question_open=True), st2, now=NOW + 60)
        self.assertEqual(acts, [])
        self.assertIn("a", st3["ho_pending"])

    def test_grace_restarts_when_the_owner_answers(self):
        st = {"ho_pending": {"a": NOW - 3600}}
        acts, st2 = self.tick(_view(owner_input_at=NOW - 300), st)
        self.assertEqual(acts, [])
        self.assertIn("a", st2["ho_pending"])
        acts, _ = self.tick(_view(owner_input_at=NOW - 16 * 60), st2)
        self.assertEqual([a.kind for a in acts], ["respawn"])
        acts, _ = self.tick(_view(owner_input_at=NOW - 300, last_assistant="## READY FOR HANDOVER"), st)
        self.assertEqual([a.kind for a in acts], ["respawn"])

    def test_pause_close_waits_for_the_dialog(self):
        self.cfg.done_handover = True
        self.projects["a"].phase = "paused"
        st = {"pause_close": {"a": NOW - 10}}
        acts, st2 = self.tick(_view(question_open=True), st)
        self.assertEqual([a.kind for a in acts if a.kind in ("handover", "stop")], [])
        self.assertIn("a", st2["pause_close"])

    def test_shutdown_does_not_type_into_a_dialog(self):
        acts, sd, _ = sw.plan_shutdown([_view(question_open=True)], self.projects, {}, self.cfg, NOW)
        self.assertEqual([a.kind for a in acts if a.name == "a"], [])

    def test_no_nudge_keepwarm_or_no_work_close(self):
        self.cfg.claude_idle = "act"
        txt = "Bitirdim, sıradaki işe geçiyorum."
        def idle(**kw):
            return sw.plan_claude_idle([_view(last_assistant=txt, **kw)], self.projects, {}, self.cfg, NOW, [],
                                       open_work=lambda _p: 3, owner_todo=lambda _p: 0)[0]
        self.assertTrue(idle())                                  # diyalog yoksa dürtülür (denetim anlamlı olsun)
        self.assertEqual(idle(question_open=True), [])
        r = snw.check_session(_view(question_open=True), self.projects["a"], {}, self.cfg, NOW, None, {})
        self.assertFalse(r["checks"]["no_question"])


class Send(unittest.TestCase):
    def test_web_handover_refuses_while_dialog_open(self):
        proc = SimpleNamespace(name="a", pid=1, cli="claude", cwd="/w", sid="s", model="", effort="")
        sent = []
        with mock.patch.object(web, "_find_running_for_action", lambda n: ("exact", [proc])), \
                mock.patch.object(web, "is_tmux_backed", lambda p: True), \
                mock.patch.object(web, "open_dialog_reason", lambda *a: "transcript"), \
                mock.patch.object(web, "apply_handover_downgrades", lambda *a, **k: sent.append("model")), \
                mock.patch.object(web, "tmux_send_keys", lambda *a, **k: sent.append("keys") or True):
            res = web._handover("a")
        self.assertEqual((res["ok"], res.get("code"), sent), (False, "question_open", []))

    def test_refused_engine_handover_is_not_left_pending(self):
        saved = {}
        state = {"ho_pending": {"a": NOW, "b": NOW}, "ho_close": {"a": "a"}}
        cfg = sw.Config(enabled=True, mode="act")
        with mock.patch.object(ws, "_local_handover", lambda *a: {"ok": False, "code": "question_open"}), \
                mock.patch.object(ws, "_target", lambda *a, **k: None), \
                mock.patch.object(ws, "_locate", lambda *a, **k: "", create=True), \
                mock.patch.object(ws.sw, "steward_lock", lambda *a: mock.MagicMock()), \
                mock.patch.object(ws.sw, "load_state", lambda *a: state), \
                mock.patch.object(ws.sw, "save_state", lambda st, *a: saved.update(st)):
            res = ws._undo_refused_handover("a", {"ok": False, "code": "question_open"}, "default")
        self.assertFalse(res["ok"])
        self.assertEqual((saved["ho_pending"], saved["ho_close"]), ({"b": NOW}, {}))

    def test_remote_facts_carry_the_dialog(self):
        v = sw.SessionView(name="a", running=True)
        ws._apply_facts(v, {"question_open": True, "owner_input_age_s": 30}, NOW, None)
        self.assertEqual((v.question_open, v.owner_input_at), (True, NOW - 30))


if __name__ == "__main__":
    unittest.main()

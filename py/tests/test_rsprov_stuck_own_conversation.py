"""TBD#419 (sahip (a), 27 Kas): takılan oturum denetimi, konuşma kimliği bilinmeyen claude oturumunda dizindeki EN YENİ
transkripte (kardeş oturumunkine) bakmaz. Kimlik yalnız sürecin kendi `sessions/<pid>.json` kaydından çözülür;
çözülemezse oturum takılmış SAYILMAZ. Yeniden açma, kararın verildiği konuşmayı sürdürür. Süreç YOK, hepsi geçici
dizin."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import spawn, stuck  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402

PID = 4242


class _Home(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        self.cwd = str(self.root / "proje")
        self.projects = self.root / "projects"
        self.sessions = self.root / "sessions"
        self.proj = self.projects / cp._encode_cwd(self.cwd)
        self.proj.mkdir(parents=True)
        self.sessions.mkdir()
        self.held = frozenset()
        for p in (mock.patch.object(cp, "PROJECTS_DIR", str(self.projects)),
                  mock.patch.object(cp, "SESSIONS_DIR", str(self.sessions)),
                  mock.patch.object(cp, "proc_stat_fields", lambda pid: ["0"] * 19 + ["777"]),
                  mock.patch.object(stuck, "is_tmux_backed", return_value=False),
                  mock.patch.object(stuck, "_ids_held_by_others", lambda name: self.held, create=True)):
            p.start()
            self.addCleanup(p.stop)

    def transcript(self, sid, last_role, mtime=1_000_000_000):
        path = self.proj / f"{sid}.jsonl"
        rows = [{"type": "user", "cwd": self.cwd, "message": {"content": "soru"}},
                {"type": "assistant", "effort": "high", "message": {"model": "claude-sonnet-5-5",
                                                                    "content": [{"type": "text", "text": "yanıt"}]}}]
        if last_role == "user":
            rows.append({"type": "user", "message": {"content": "cevapsız"}})
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def record(self, sid="kendi", start="777"):
        body = {"pid": PID, "sessionId": sid, "procStart": start, "cwd": self.cwd}
        (self.sessions / f"{PID}.json").write_text(json.dumps(body), encoding="utf-8")

    def session(self, sid=None, cli="claude"):
        return SimpleNamespace(name="vc1", pid=PID, cwd=self.cwd, model="spawn-m", permission_mode="auto",
                               effort="spawn-e", cli=cli, sid=sid, cpu=0.0)

    def recover(self, info):
        def kill(*a, **k):          # claude kapanırken kendi kaydını siler
            (self.sessions / f"{PID}.json").unlink(missing_ok=True)
            return "killed"

        with mock.patch.object(stuck, "kill_session_and_parent", side_effect=kill) as kp, \
                mock.patch.object(stuck, "spawn_session", return_value="tmux") as sp:
            out = stuck.recover_stuck(info, display=":0")
        return out, kp, sp


class FindStuckTest(_Home):
    def test_sibling_conversation_never_decides(self):
        self.transcript("kardes", "user", mtime=2_000_000_000)
        self.assertEqual(stuck.find_stuck([self.session()]), [])
        self.assertEqual(stuck.find_stuck([self.session(sid="")]), [])

    def test_own_answered_conversation_wins_over_a_stuck_sibling(self):
        self.transcript("kardes", "user", mtime=2_000_000_000)
        self.transcript("kendi", "assistant")
        self.record()
        self.assertEqual(stuck.find_stuck([self.session()]), [])

    def test_own_record_decides(self):
        self.transcript("kardes", "assistant", mtime=2_000_000_000)
        self.transcript("kendi", "user")
        self.record()
        found = stuck.find_stuck([self.session()])
        self.assertEqual([(i.session.name, i.last_role, i.sid) for i in found], [("vc1", "user", "kendi")])

    def test_untrusted_record_means_not_stuck(self):
        self.transcript("kardes", "user", mtime=2_000_000_000)
        self.transcript("kendi", "user")
        self.record(start="1")
        self.assertEqual(stuck.find_stuck([self.session()]), [])

    def test_known_sid_is_kept(self):
        self.transcript("bilinen", "user")
        self.transcript("kendi", "assistant", mtime=2_000_000_000)
        self.record()
        self.assertEqual([i.sid for i in stuck.find_stuck([self.session(sid="bilinen")])], ["bilinen"])

    def test_ucli_is_asked_as_before(self):
        asked = []
        prov = SimpleNamespace(wants_stuck_recovery=lambda: True, live_busy=lambda cwd, sid: False,
                               last_message_role=lambda cwd, sid: asked.append((cwd, sid)) or "user")
        with mock.patch.object(stuck, "get_provider", return_value=prov):
            found = stuck.find_stuck([self.session(cli="ucli")])
        self.assertEqual(asked, [(self.cwd, None)])
        self.assertEqual([i.sid for i in found], [None])


class RecoverStuckTest(_Home):
    def test_resumes_the_conversation_the_decision_was_made_on(self):
        self.transcript("kendi", "user")
        self.transcript("kardes", "assistant", mtime=2_000_000_000)
        self.record()
        info = stuck.find_stuck([self.session()])[0]
        (self.sessions / f"{PID}.json").unlink()            # karardan sonra kayıt gitse de kimlik değişmez
        out, _, sp = self.recover(info)
        self.assertEqual(out, "recovered (tmux)")
        self.assertEqual(sp.call_args.kwargs["resume_id"], "kendi")
        self.assertEqual((sp.call_args.kwargs["model"], sp.call_args.kwargs["effort"]), ("claude-sonnet-5-5", "high"))

    def test_hand_built_info_resolves_the_own_record_before_the_kill(self):
        self.transcript("kendi", "user")
        self.record()
        _, _, sp = self.recover(SimpleNamespace(session=self.session()))
        self.assertEqual(sp.call_args.kwargs["resume_id"], "kendi")

    def test_unknown_conversation_is_left_alone(self):
        self.transcript("kardes", "user", mtime=2_000_000_000)
        out, kp, sp = self.recover(SimpleNamespace(session=self.session()))
        self.assertTrue(out.startswith("skipped"), out)
        kp.assert_not_called()
        sp.assert_not_called()

    def test_conversation_held_by_another_session_is_left_alone(self):
        self.transcript("kendi", "user")
        self.held = frozenset({"kendi"})
        out, kp, sp = self.recover(SimpleNamespace(session=self.session(sid="kendi")))
        self.assertTrue(out.startswith("skipped"), out)
        kp.assert_not_called()
        sp.assert_not_called()

    def test_ucli_keeps_its_own_resume_lookup(self):
        _, _, sp = self.recover(SimpleNamespace(session=self.session(sid="abc", cli="ucli"), sid="abc"))
        self.assertIsNone(sp.call_args.kwargs.get("resume_id"))


class SpawnResumeIdTest(unittest.TestCase):
    def kind(self, **kw):
        provider = spawn.get_provider("claude")
        with mock.patch.object(provider, "resolve_resume_id", return_value="tahmin00-x") as resolve:
            out = spawn.spawn_session("zz_t", "/tmp", "claude-sonnet-5-5", display=":9", dry_run=True, cli="claude",
                                      **kw)
        return out.split()[1], resolve.call_count

    def test_given_conversation_is_resumed_without_guessing(self):
        with mock.patch.object(spawn, "_ids_held_by_others", return_value=frozenset()):
            self.assertEqual(self.kind(resume_id="karar000-y"), ("resume:karar000", 0))
            self.assertEqual(self.kind(resume_id=None), ("resume:tahmin00", 1))
            self.assertEqual(self.kind(resume_id=""), ("resume:tahmin00", 1))

    def test_force_new_wins(self):
        self.assertEqual(self.kind(resume_id="karar000-y", force_new=True), ("new", 0))


if __name__ == "__main__":
    unittest.main()

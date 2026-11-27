"""rs/prov S1 (sahip onayı (a), 27 Kas): konuşma kimliği bilinmeyen claude oturumunda devir ve takılan oturumun yeniden
açılışı model/effort'u dizindeki EN YENİ transkriptten okumaz. Kimlik yalnız sürecin kendi `sessions/<pid>.json`
kaydından çözülür (pid + procStart + cwd doğrulaması); çözülemezse açılış değeri. Süreç YOK, hepsi geçici dizin."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import handover, stuck  # noqa: E402
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
        self.alive = {PID: "777"}

        def stat(pid):
            fields = ["0"] * 20
            fields[19] = self.alive[pid] if pid in self.alive else self._dead()
            return fields

        for p in (mock.patch.object(cp, "PROJECTS_DIR", str(self.projects)),
                  mock.patch.object(cp, "SESSIONS_DIR", str(self.sessions)),
                  mock.patch.object(cp, "proc_stat_fields", stat)):
            p.start()
            self.addCleanup(p.stop)
        self.transcript("kardes", "claude-opus-5-5", "max", mtime=2_000_000_000)

    def _dead(self):
        raise OSError("süreç yok")

    def transcript(self, sid, model, effort, mtime=1_000_000_000, file_cwd=None):
        path = self.proj / f"{sid}.jsonl"
        rows = [{"type": "user", "cwd": file_cwd or self.cwd},
                {"type": "assistant", "effort": effort, "message": {"model": model}}]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def record(self, sid="kendi", pid=PID, file_pid=None, start="777", cwd=None):
        body = {"pid": pid if file_pid is None else file_pid, "sessionId": sid, "procStart": start,
                "cwd": self.cwd if cwd is None else cwd}
        (self.sessions / f"{pid}.json").write_text(json.dumps(body), encoding="utf-8")

    def live(self, sid=None, pid=PID):
        return (cp.live_or_spawn_model("claude", self.cwd, sid, "spawn-m", pid=pid),
                cp.live_or_spawn_effort("claude", self.cwd, sid, "spawn-e", pid=pid))


SPAWN = ("spawn-m", "spawn-e")


class OwnSessionRecordTest(_Home):
    def test_sibling_newest_transcript_is_never_used(self):
        self.assertEqual(self.live(), SPAWN)

    def test_no_pid_means_spawn_values(self):
        self.assertEqual(cp.live_or_spawn_model("claude", self.cwd, None, "spawn-m"), "spawn-m")
        self.assertEqual(cp.live_or_spawn_effort("claude", self.cwd, "", "spawn-e"), "spawn-e")

    def test_own_record_resolves_the_conversation(self):
        self.transcript("kendi", "claude-sonnet-5-5", "high")
        self.record()
        self.assertEqual(self.live(), ("claude-sonnet-5-5", "high"))
        self.assertEqual(self.live(sid=""), ("claude-sonnet-5-5", "high"))

    def test_known_sid_wins_over_the_record(self):
        self.transcript("kendi", "claude-sonnet-5-5", "high")
        self.record()
        self.assertEqual(self.live(sid="kardes"), ("claude-opus-5-5", "max"))
        self.assertEqual(self.live(sid="yok"), SPAWN)

    def test_untrusted_records_are_refused(self):
        self.transcript("kendi", "claude-sonnet-5-5", "high")
        cases = {"başka süreç": dict(file_pid=PID + 1), "bayat": dict(start="1"), "kanıtsız": dict(start=""),
                 "başka cwd": dict(cwd=str(self.root / "baska")), "boş sid": dict(sid=""),
                 "dosyasız sid": dict(sid="yok"), "yol dışı sid": dict(sid="../x")}
        for label, kw in cases.items():
            with self.subTest(label):
                self.record(**kw)
                self.assertEqual(self.live(), SPAWN)

    def test_dead_process_record_is_refused(self):
        self.transcript("kendi", "claude-sonnet-5-5", "high")
        self.record()
        self.alive.clear()
        self.assertEqual(self.live(), SPAWN)

    def test_transcript_of_another_cwd_with_the_same_folder_name_is_refused(self):
        self.transcript("kendi", "claude-sonnet-5-5", "high", file_cwd=self.cwd + "_baska")
        self.record()
        self.assertEqual(self.live(), SPAWN)


class CallersTest(_Home):
    """Devir ve yeniden açma: pid okuyuculara ulaşır; yeniden açma değeri süreç ÖLDÜRÜLMEDEN okur."""

    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(handover, "diag_log", lambda *a, **k: None),
                  mock.patch.object(handover, "default_handover_effort", lambda provider: "high")):
            p.start()
            self.addCleanup(p.stop)

    def provider(self):
        sent = []
        prov = SimpleNamespace(
            prompt_cache_ttl_seconds=lambda: None,
            handover_model_downgrade=lambda m: sent.append(("model-in", m)),
            handover_effort_downgrade=lambda cur, target: sent.append(("effort-in", cur)))
        return prov, sent

    def test_handover_reads_the_own_conversation(self):
        self.transcript("kendi", "claude-sonnet-5-5", "high")
        self.record()
        prov, sent = self.provider()
        res = handover.apply_handover_downgrades(prov, "s", "claude", self.cwd, None, "spawn-m", "spawn-e", pid=PID)
        self.assertEqual(res.model, "claude-sonnet-5-5")
        self.assertEqual(sent, [("model-in", "claude-sonnet-5-5"), ("effort-in", "high")])

    def test_handover_without_a_record_uses_spawn_values(self):
        prov, sent = self.provider()
        handover.apply_handover_downgrades(prov, "s", "claude", self.cwd, None, "spawn-m", "spawn-e", pid=PID)
        handover.downgrade_effort_for_handover(prov, "s", "claude", self.cwd, None, "spawn-e", pid=PID)
        self.assertEqual(sent, [("model-in", "spawn-m"), ("effort-in", "spawn-e"), ("effort-in", "spawn-e")])

    def test_effort_wrapper_passes_the_pid(self):
        self.transcript("kendi", "claude-sonnet-5-5", "high")
        self.record()
        prov, sent = self.provider()
        handover.downgrade_effort_for_handover(prov, "s", "claude", self.cwd, None, "spawn-e", pid=PID)
        self.assertEqual(sent, [("effort-in", "high")])

    def recover(self):
        s = SimpleNamespace(name="vc1", pid=PID, cwd=self.cwd, model="spawn-m", permission_mode="auto",
                            effort="spawn-e", cli="claude", sid=None)

        def kill(*a, **k):          # claude kapanırken kaydını siler, süreç de gider
            self.alive.clear()
            (self.sessions / f"{PID}.json").unlink(missing_ok=True)
            return "killed"

        with mock.patch.object(stuck, "kill_session_and_parent", side_effect=kill) as kp, \
                mock.patch.object(stuck, "_ids_held_by_others", return_value=frozenset()), \
                mock.patch.object(stuck, "spawn_session", return_value="tmux") as sp:
            stuck.recover_stuck(SimpleNamespace(session=s), display=":0")
        if not sp.called:
            kp.assert_not_called()
            return None
        return sp.call_args.kwargs["model"], sp.call_args.kwargs["effort"]

    def test_recovery_reads_the_own_record_before_the_kill(self):
        self.transcript("kendi", "claude-sonnet-5-5", "high")
        self.record()
        self.assertEqual(self.recover(), ("claude-sonnet-5-5", "high"))

    def test_recovery_without_a_record_leaves_the_session_alone(self):   # TBD#419: konuşma bilinmiyorsa dokunulmaz
        self.assertIsNone(self.recover())


if __name__ == "__main__":
    unittest.main()

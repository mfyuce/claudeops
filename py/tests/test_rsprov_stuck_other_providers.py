"""TBD#425 (sahip (a), 27 Kas): takılan oturum denetimi codex, agy ve copilot'ta da yalnız konuşma kimliği KESİN
bilinen oturumda karar verir: kimlik süreç komut satırındaki devam kimliğidir (cwd'deki en yeni dosya, cwd önbelleği ve
ad eşleşmesi tahmindir). Kimlik yoksa ya da tam eşleşen kayıt yoksa oturum takılmış SAYILMAZ; yeniden açma kararın
verildiği konuşmayı sürdürür. TBD#441 (= a, 28 Kas): codex ve agy'de komut satırı kimliğinin güncel olduğuna dair kanıt
yok, otomatik kurtarma KAPALI (`wants_stuck_recovery()` False): kesin kimlikte bile karar verilmez, elle kurulan
`StuckInfo` da öldürülmez. Süreç YOK (komut satırı sahte), hepsi geçici dizin."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import psutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import spawn, stuck  # noqa: E402
from claudeops.providers import agy_provider as ap  # noqa: E402
from claudeops.providers import codex_provider as xp  # noqa: E402
from claudeops.providers import copilot_provider as pp  # noqa: E402

PID = 4242
OWN = "11111111-1111-1111-1111-111111111111"
SIBLING = "22222222-2222-2222-2222-222222222222"


def _field(number, data):
    """Kısa protobuf uzunluk alanı (etiket varint'i en çok iki bayt, veri 128 bayttan kısa)."""
    tag = number << 3 | 2
    head = bytes([tag]) if tag < 128 else bytes([tag & 0x7F | 0x80, tag >> 7])
    return head + bytes([len(data)]) + data


class _Base(unittest.TestCase):
    cli = ""
    FLAG: tuple = ()

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        self.cwd = str(self.root / "proje")
        self.held = frozenset()
        self.argv = [self.cli]
        self.patch(stuck, "is_tmux_backed", return_value=False)
        self.patch(stuck, "_ids_held_by_others", side_effect=lambda name: self.held)
        # Süreç bütün kayıtlardan SONRA başlamış (`started`), copilot yalnız komut satırındaki konuşmayı tutuyor
        # (`held`, `None` = komut satırındaki kimlik): kimliğin bayatlığı `test_rsprov_stuck_argv_stale.py`da.
        self.started = 3_000_000_000
        self.held_files = None
        self.patch(psutil, "Process", side_effect=lambda pid: SimpleNamespace(
            cmdline=lambda: list(self.argv), create_time=lambda: self.started, open_files=self.open_files))

    def open_files(self):
        """copilot'un `session-state/<kimlik>/inuse.<pid>.hold` dosyaları (ölçüm: 1.0.117 her açık konuşmada tutar)."""
        held = self.held_files
        if held is None:
            held = [a for i, a in enumerate(self.argv) if i and self.argv[i - 1] == "--resume"]
        return [SimpleNamespace(path=f"/h/.copilot/session-state/{sid}/inuse.{PID}.hold", fd=20 + i)
                for i, sid in enumerate(held)]

    def patch(self, target, name, *new, **kw):
        p = mock.patch.object(target, name, *new, **kw)
        p.start()
        self.addCleanup(p.stop)

    def session(self, sid=None):
        self.argv = [self.cli, *((*self.FLAG, sid) if sid else ())]
        return SimpleNamespace(name="vc1", pid=PID, cwd=self.cwd, model="m", permission_mode="auto", effort="high",
                               cli=self.cli, sid=sid, cpu=0.0)

    def recover(self, info):
        with mock.patch.object(stuck, "kill_session_and_parent", return_value="killed") as kp, \
                mock.patch.object(stuck, "spawn_session", return_value="tmux") as sp:
            out = stuck.recover_stuck(info, display=":0")
        return out, kp, sp


class _Cases:
    """Her sağlayıcıda aynı kural; `conversation(sid, son_rol, yeni)` kaydı sağlayıcının kendi biçiminde yazar."""

    def test_unknown_id_is_never_stuck(self):
        self.conversation(SIBLING, "user", newer=True)
        self.assertEqual(stuck.find_stuck([self.session()]), [])
        self.assertEqual(stuck.find_stuck([self.session(sid="")]), [])

    def test_missing_exact_record_is_never_stuck(self):
        self.conversation(SIBLING, "user", newer=True)
        for sid in (OWN, OWN[:8], "--last"):
            with self.subTest(sid=sid):
                self.assertEqual(stuck.find_stuck([self.session(sid=sid)]), [])

    def test_own_answered_conversation_wins_over_a_stuck_sibling(self):
        self.conversation(OWN, "assistant")
        self.conversation(SIBLING, "user", newer=True)
        self.assertEqual(stuck.find_stuck([self.session(sid=OWN)]), [])

    def test_decision_and_resume_use_the_same_conversation(self):
        self.conversation(OWN, "user")
        self.conversation(SIBLING, "assistant", newer=True)
        found = stuck.find_stuck([self.session(sid=OWN)])
        self.assertEqual([(i.sid, i.last_role) for i in found], [(OWN, "user")])
        out, kp, sp = self.recover(found[0])
        self.assertEqual(out, "recovered (tmux)")
        kp.assert_called_once()
        self.assertEqual(sp.call_args.kwargs["resume_id"], OWN)

    def test_hand_built_info_takes_the_id_of_the_process(self):
        _, _, sp = self.recover(SimpleNamespace(session=self.session(sid=OWN)))
        self.assertEqual(sp.call_args.kwargs["resume_id"], OWN)

    def test_unknown_conversation_is_left_alone(self):
        out, kp, sp = self.recover(SimpleNamespace(session=self.session()))
        self.assertTrue(out.startswith("skipped"), out)
        kp.assert_not_called()
        sp.assert_not_called()

    def test_conversation_held_by_another_session_is_left_alone(self):
        self.held = frozenset({OWN})
        out, kp, sp = self.recover(SimpleNamespace(session=self.session(sid=OWN), sid=OWN))
        self.assertTrue(out.startswith("skipped"), out)
        kp.assert_not_called()
        sp.assert_not_called()


class _Disabled:
    """TBD#441: codex/agy oturumu, konuşması kesin ve cevapsız olsa bile takılmış sayılmaz ve öldürülmez."""

    def test_provider_opts_out(self):
        self.assertFalse(spawn.get_provider(self.cli).wants_stuck_recovery())

    def test_exact_unanswered_conversation_is_never_stuck(self):
        self.conversation(OWN, "user")
        self.assertEqual(stuck.find_stuck([self.session(sid=OWN)]), [])

    def test_hand_built_info_is_left_alone(self):
        self.conversation(OWN, "user")
        for info in (SimpleNamespace(session=self.session(sid=OWN)),
                     SimpleNamespace(session=self.session(sid=OWN), sid=OWN)):
            out, kp, sp = self.recover(info)
            self.assertTrue(out.startswith("skipped"), out)
            kp.assert_not_called()
            sp.assert_not_called()


class CodexTest(_Disabled, _Base):
    cli = "codex"
    FLAG = ("resume",)

    def setUp(self):
        super().setUp()
        self.day = self.root / "sessions" / "2026" / "11" / "27"
        self.day.mkdir(parents=True)
        self.patch(xp, "SESSIONS_DIR", str(self.root / "sessions"))

    def conversation(self, sid, last_role, newer=False):
        def message(role, kind, text):
            return {"type": "response_item", "payload": {"type": "message", "role": role,
                                                         "content": [{"type": kind, "text": text}]}}
        rows = [{"type": "session_meta", "payload": {"cwd": self.cwd, "id": sid}},
                message("user", "input_text", "soru"), message("assistant", "output_text", "yanıt")]
        if last_role == "user":
            rows.append(message("user", "input_text", "cevapsız"))
        path = self.day / f"rollout-2026-11-27T10-00-00-{sid}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        os.utime(path, (2_000_000_000, 2_000_000_000) if newer else (1_000_000_000, 1_000_000_000))

    def test_other_readers_still_fall_back_to_the_newest_rollout_of_the_cwd(self):
        self.conversation(SIBLING, "user", newer=True)
        provider = xp.CodexProvider()
        self.assertEqual(provider.last_exchange(self.cwd, None)["assistant"], "yanıt")
        self.assertEqual(provider.full_history(self.cwd, OWN)[-1]["text"], "cevapsız")
        self.assertIsNone(provider.last_message_role(self.cwd, None))
        self.assertIsNone(provider.last_message_role(self.cwd, OWN))
        self.assertEqual(provider.last_message_role(self.cwd, SIBLING), "user")


class AgyTest(_Disabled, _Base):
    cli = "agy"
    FLAG = ("--conversation",)

    def setUp(self):
        super().setUp()
        self.conversations = self.root / "conversations"
        self.conversations.mkdir()
        self.cache = self.root / "last_conversations.json"
        self.patch(ap, "CONVERSATIONS_DIR", str(self.conversations))
        self.patch(ap, "CONVERSATIONS_CACHE", str(self.cache))
        self.patch(ap, "_load_agy_sids", side_effect=AssertionError("karar öğrenilen eşleşmeye bakmaz"))
        self.patch(ap, "_remember_agy_sid", side_effect=AssertionError("karar yolu yazmaz"))

    def conversation(self, sid, last_role, newer=False):
        user = (14, _field(19, _field(2, b"soru")))
        answer = (15, _field(20, _field(1, b"yanit")))
        steps = [user, answer] + ([user] if last_role == "user" else [])
        conn = sqlite3.connect(str(self.conversations / f"{sid}.db"))
        with conn:
            conn.execute("CREATE TABLE steps (idx INTEGER, step_type INTEGER, step_payload BLOB)")
            conn.executemany("INSERT INTO steps VALUES (?, ?, ?)",
                             [(i, t, p) for i, (t, p) in enumerate(steps)])
        conn.close()
        if newer:
            self.cache.write_text(json.dumps({self.cwd: sid}), encoding="utf-8")

    def guessed(self, sid):
        """Keşfin cwd önbelleğinden yapıştırdığı kimlik: `Session.sid` dolu, komut satırında yok."""
        s = self.session()
        s.sid = sid
        return s

    def test_id_guessed_from_the_cwd_cache_never_decides(self):
        self.conversation(SIBLING, "user", newer=True)
        self.assertEqual(stuck.find_stuck([self.guessed(SIBLING)]), [])
        out, kp, sp = self.recover(SimpleNamespace(session=self.guessed(SIBLING)))
        self.assertTrue(out.startswith("skipped"), out)
        kp.assert_not_called()
        sp.assert_not_called()


class CopilotTest(_Cases, _Base):
    cli = "copilot"
    FLAG = ("--resume",)

    def setUp(self):
        super().setUp()
        self.db = str(self.root / "session-store.db")
        self.patch(pp, "SESSION_STORE_DB", self.db)
        conn = sqlite3.connect(self.db)
        with conn:
            conn.execute("CREATE TABLE sessions (id TEXT, cwd TEXT, updated_at INTEGER)")
            conn.execute("CREATE TABLE turns (session_id TEXT, turn_index INTEGER, user_message TEXT, "
                         "assistant_response TEXT)")
        conn.close()

    def conversation(self, sid, last_role, newer=False):
        conn = sqlite3.connect(self.db)
        with conn:
            conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (sid, self.cwd, 2 if newer else 1))
            conn.execute("INSERT INTO turns VALUES (?, 0, 'soru', 'yanıt')", (sid,))
            if last_role == "user":
                conn.execute("INSERT INTO turns VALUES (?, 1, 'cevapsız', NULL)", (sid,))
        conn.close()


class UcliUnchangedTest(_Base):
    cli = "ucli"

    def test_decision_and_recovery_are_as_before(self):
        asked = []
        provider = SimpleNamespace(wants_stuck_recovery=lambda: True, live_busy=lambda cwd, sid: False,
                                   last_message_role=lambda cwd, sid: asked.append((cwd, sid)) or "user",
                                   permission_modes=lambda: ["read"])
        s = self.session()
        s.sid = "vc1"
        with mock.patch.object(stuck, "get_provider", return_value=provider):
            found = stuck.find_stuck([s])
            _, kp, sp = self.recover(found[0])
        self.assertEqual(asked, [(self.cwd, "vc1")])
        kp.assert_called_once()
        self.assertIsNone(sp.call_args.kwargs.get("resume_id"))


class SpawnResumeIdTest(unittest.TestCase):
    def test_every_provider_resumes_the_given_conversation_without_guessing(self):
        flags = {"codex": f"resume {OWN}", "agy": f"--conversation {OWN}", "copilot": f"--resume {OWN}"}
        for cli, flag in flags.items():
            provider = spawn.get_provider(cli)
            module = sys.modules[type(provider).__module__]
            with self.subTest(cli=cli), \
                    mock.patch.object(provider, "resolve_resume_id", side_effect=AssertionError("tahmin yok")), \
                    mock.patch.object(provider, "resolve_effort", return_value="high"), \
                    mock.patch.object(module, "resolved_binary", return_value=cli), \
                    mock.patch.object(pp, "byok_env_for", return_value={}), \
                    mock.patch.object(pp, "_BYOK_ENV_FILE", "/yok/byok"), \
                    mock.patch.object(pp, "_BYOK_ENV_MANAGED_MARKER", "/yok/byok.managed"), \
                    mock.patch.object(spawn, "spawn_priority_prefix", return_value=""):
                out = spawn.spawn_session("zz_t", "/tmp", "m", display=":9", dry_run=True, cli=cli, resume_id=OWN)
            self.assertIn(f"resume:{OWN[:8]}", out)
            self.assertIn(flag, out)


if __name__ == "__main__":
    unittest.main()

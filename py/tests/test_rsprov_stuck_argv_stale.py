"""TBD#427 (sahip): takılma kararı yalnız konuşma kimliği KESİN bilinen oturumda verilir. Komut satırındaki devam kimliği
CLI içinde `/new`, `/resume` ile bayatlar; eski konuşma cevapsız kullanıcı mesajıyla bitiyorsa oturum öldürülüp ESKİ
konuşmayla açılırdı. Kurallar (rs/prov, 28 Kas):
- claude: yalnız sürecin kendi `sessions/<pid>.json` kaydı (claude 2.1.332 konuşma değişince kaydı yeniler); komut
  satırı kimliği kayıtsız karar vermez.
- copilot: süreç yalnız komut satırındaki konuşmanın `session-state/<kimlik>/inuse.<pid>.hold` dosyasını tutuyorsa
  (ölçüm, 1.0.117: `/new` yeni konuşmanın dosyasını da açar, eskisini bırakmaz).
- codex, agy: canlı konuşmayı gösteren yerel kanıt yok; yalnız AYNI dizinde süreç başladıktan sonra yazılmış başka
  konuşma varsa karar verilmez.
Süreç YOK (sahte `psutil.Process`), hepsi geçici dizin."""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import psutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_rsprov_stuck_other_providers import (OWN, PID, SIBLING, AgyTest, CodexTest,  # noqa: E402
                                                CopilotTest)
from test_rsprov_stuck_own_conversation import _Home  # noqa: E402

from claudeops import stuck  # noqa: E402

START = 1_500_000_000           # sürecin başlangıcı: kayıtlar 1e9 (önce) ya da 2e9 (sonra)


class _Stale:
    def assert_left_alone(self, s):
        self.assertEqual(stuck.find_stuck([s]), [])
        out, kp, sp = self.recover(SimpleNamespace(session=s))
        self.assertTrue(out.startswith("skipped"), out)
        kp.assert_not_called()
        sp.assert_not_called()

    def assert_decides(self, s):
        self.assertEqual([i.sid for i in stuck.find_stuck([s])], [OWN])


class ClaudeArgvTest(_Home):
    def test_argv_id_loses_to_the_live_record(self):
        self.transcript("eski", "user")
        self.transcript("kendi", "assistant", mtime=2_000_000_000)
        self.record()
        self.assertEqual(stuck.find_stuck([self.session(sid="eski")]), [])

    def test_argv_id_without_a_record_never_decides(self):
        self.transcript("eski", "user")
        self.assertEqual(stuck.find_stuck([self.session(sid="eski")]), [])
        out, kp, sp = self.recover(SimpleNamespace(session=self.session(sid="eski")))
        self.assertTrue(out.startswith("skipped"), out)
        kp.assert_not_called()
        sp.assert_not_called()


class CodexArgvTest(_Stale, CodexTest):
    def setUp(self):
        super().setUp()
        self.started = START

    def test_newer_conversation_in_the_same_cwd_means_the_argv_id_may_be_stale(self):
        self.conversation(OWN, "user")
        self.conversation(SIBLING, "assistant", newer=True)
        self.assert_left_alone(self.session(sid=OWN))

    def test_newer_conversation_elsewhere_or_older_one_here_does_not_block(self):
        self.conversation(OWN, "user")
        self.conversation(SIBLING, "assistant")
        other = self.day / "rollout-2026-11-27T11-00-00-33333333-3333-3333-3333-333333333333.jsonl"
        other.write_text(json.dumps({"type": "session_meta", "payload": {"cwd": "/baska", "id": "x"}}) + "\n",
                         encoding="utf-8")
        os.utime(other, (2_000_000_000, 2_000_000_000))
        self.assert_decides(self.session(sid=OWN))

    def test_own_conversation_written_after_start_is_fine(self):
        self.conversation(OWN, "user", newer=True)
        self.assert_decides(self.session(sid=OWN))

    def test_unreadable_newer_conversation_means_unknown(self):
        self.conversation(OWN, "user")
        bad = self.day / "rollout-2026-11-27T11-00-00-33333333-3333-3333-3333-333333333333.jsonl"
        bad.write_text("{bozuk\n", encoding="utf-8")
        os.utime(bad, (2_000_000_000, 2_000_000_000))
        self.assert_left_alone(self.session(sid=OWN))

    def test_unknown_start_time_means_unknown(self):
        self.conversation(OWN, "user")
        self.started = None
        with mock.patch.object(psutil, "Process", side_effect=lambda pid: SimpleNamespace(
                cmdline=lambda: list(self.argv), create_time=mock.Mock(side_effect=psutil.AccessDenied(PID)))):
            self.assertEqual(stuck.find_stuck([self.session(sid=OWN)]), [])


class AgyArgvTest(_Stale, AgyTest):
    def setUp(self):
        super().setUp()
        self.started = START

    def conversation(self, sid, last_role, newer=False):
        super().conversation(sid, last_role, newer)
        t = 2_000_000_000 if newer else 1_000_000_000
        os.utime(self.conversations / f"{sid}.db", (t, t))

    def test_cwd_cache_moved_to_a_newer_conversation_means_the_argv_id_may_be_stale(self):
        self.conversation(OWN, "user")
        self.conversation(SIBLING, "assistant", newer=True)
        self.assert_left_alone(self.session(sid=OWN))

    def test_cache_pointing_at_an_older_conversation_does_not_block(self):
        self.conversation(OWN, "user")
        self.conversation(SIBLING, "assistant")
        self.cache.write_text(json.dumps({self.cwd: SIBLING}), encoding="utf-8")
        self.assert_decides(self.session(sid=OWN))

    def test_cache_on_the_own_conversation_or_another_cwd_does_not_block(self):
        self.conversation(OWN, "user", newer=True)
        self.conversation(SIBLING, "assistant", newer=True)
        for cache in ({self.cwd: OWN}, {"/baska": SIBLING}, {}):
            with self.subTest(cache=cache):
                self.cache.write_text(json.dumps(cache), encoding="utf-8")
                self.assert_decides(self.session(sid=OWN))

    def test_unreadable_cache_means_unknown(self):
        self.conversation(OWN, "user")
        for body in ("{bozuk", "[1]"):
            with self.subTest(body=body):
                self.cache.write_text(body, encoding="utf-8")
                self.assertEqual(stuck.find_stuck([self.session(sid=OWN)]), [])


class CopilotArgvTest(_Stale, CopilotTest):
    def test_only_the_argv_conversation_held_decides(self):
        self.conversation(OWN, "user")
        self.held_files = [OWN]
        self.assert_decides(self.session(sid=OWN))

    def test_another_held_conversation_means_the_argv_id_may_be_stale(self):
        self.conversation(OWN, "user")
        for held in ([OWN, SIBLING], [SIBLING], []):
            with self.subTest(held=held):
                self.held_files = held
                self.assert_left_alone(self.session(sid=OWN))

    def test_hold_of_another_pid_is_not_ours(self):
        self.conversation(OWN, "user")
        self.held_files = []
        with mock.patch.object(self, "open_files", return_value=[
                SimpleNamespace(path=f"/h/.copilot/session-state/{OWN}/inuse.{PID + 1}.hold", fd=20)]):
            self.assertEqual(stuck.find_stuck([self.session(sid=OWN)]), [])

    def test_unreadable_open_files_means_unknown(self):
        self.conversation(OWN, "user")
        with mock.patch.object(self, "open_files", side_effect=psutil.AccessDenied(PID)):
            self.assertEqual(stuck.find_stuck([self.session(sid=OWN)]), [])


# Miras alınan ortak durumlar kendi dosyalarında koşar; burada yalnız bayat kimlik durumları.
for _cls in (CodexArgvTest, AgyArgvTest, CopilotArgvTest):
    for _name in [n for n in dir(_cls) if n.startswith("test_")]:
        if _name not in _cls.__dict__:
            setattr(_cls, _name, None)
del CodexTest, AgyTest, CopilotTest, _Home


if __name__ == "__main__":
    unittest.main()

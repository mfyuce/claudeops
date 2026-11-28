"""TBD#427 (sahip): takılma kararı yalnız konuşma kimliği KESİN bilinen oturumda verilir. Komut satırındaki devam kimliği
CLI içinde `/new`, `/resume` ile bayatlar; eski konuşma cevapsız kullanıcı mesajıyla bitiyorsa oturum öldürülüp ESKİ
konuşmayla açılırdı. Kurallar (rs/prov, 28 Kas):
- claude: yalnız sürecin kendi `sessions/<pid>.json` kaydı (claude 2.1.332 konuşma değişince kaydı yeniler); komut
  satırı kimliği kayıtsız karar vermez.
- copilot: süreç yalnız komut satırındaki konuşmanın `session-state/<kimlik>/inuse.<pid>.hold` dosyasını tutuyorsa
  (ölçüm, 1.0.117: `/new` yeni konuşmanın dosyasını da açar, eskisini bırakmaz).
- codex, agy: canlı konuşmayı gösteren yerel kanıt yok; otomatik kurtarma kapalı (TBD#441 = a,
  `test_rsprov_stuck_other_providers.py`).
Süreç YOK (sahte `psutil.Process`), hepsi geçici dizin."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import psutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_rsprov_stuck_other_providers import OWN, PID, SIBLING, CopilotTest  # noqa: E402
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
for _cls in (CopilotArgvTest,):
    for _name in [n for n in dir(_cls) if n.startswith("test_")]:
        if _name not in _cls.__dict__:
            setattr(_cls, _name, None)
del CopilotTest, _Home


if __name__ == "__main__":
    unittest.main()

"""rs-prov TODO (takılma kurtarma): `_ids_held_by_others` süreç keşfi patlarsa spawn yolu eski davranışa (boş küme) düşer,
ama takılma kurtarması "konuşmayı başka canlı oturum tutuyor mu" sorusunu cevaplayamadan öldürüp yeniden açmamalı:
kapalı yön = süreç öldürülmez, "skipped: ..." döner. Süreç YOK."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import spawn, stuck  # noqa: E402


def _boom(**_k):
    raise OSError("proc taraması patladı")


class HeldDiscoveryFailsTest(unittest.TestCase):
    def test_spawn_path_still_falls_back_to_empty(self):
        with mock.patch.object(spawn, "find_sessions", side_effect=_boom):
            held = spawn._ids_held_by_others("vc1")
        self.assertEqual(set(held), set())
        self.assertFalse("x" in held)

    def test_stuck_recovery_does_not_kill_when_discovery_fails(self):
        info = SimpleNamespace(session=SimpleNamespace(name="vc1", pid=4242, cwd="/yok", model="m",
                                                       permission_mode="auto", effort="e", cli="claude",
                                                       sid="kendi", cpu=0.0),
                               sid="kendi")
        with mock.patch.object(spawn, "find_sessions", side_effect=_boom), \
                mock.patch.object(stuck, "kill_session_and_parent") as kp, \
                mock.patch.object(stuck, "spawn_session") as sp:
            out = stuck.recover_stuck(info, display=":0")
        self.assertTrue(out.startswith("skipped:"), out)
        kp.assert_not_called()
        sp.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""ucli devir hataları (TBD#156): (1) fresh=True geçmişi arşive taşır (ad aynı kalır), (2) web._handover ucli'yi reddetmez.
Gerçek spawn/tmux/ağ YOK; dosyalar geçici dizinde."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_client as uc  # noqa: E402
from claudeops.commands import web  # noqa: E402
from claudeops.providers.ucli_provider import UcliProvider  # noqa: E402


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = os.path.join(self.tmp.name, "chat")
        os.makedirs(self.d)
        p = mock.patch.object(uc, "chat_session_dirs", lambda cwd: [self.d])
        p.start()
        self.addCleanup(p.stop)

    def put(self, name, text="x"):
        with open(os.path.join(self.d, name), "w") as f:
            f.write(text)

    def test_moves_history_and_status_keeps_others(self):
        self.put("cops.jsonl", "hist")
        self.put("cops.status.json", "{}")
        self.put("other.jsonl")
        moved = uc.archive_session_files("/w", "cops", stamp=111)
        self.assertEqual(len(moved), 2)
        self.assertFalse(os.path.exists(os.path.join(self.d, "cops.jsonl")))
        self.assertFalse(os.path.exists(os.path.join(self.d, "cops.status.json")))
        with open(os.path.join(self.d, "archive", "cops.111.jsonl")) as f:
            self.assertEqual(f.read(), "hist")
        self.assertTrue(os.path.exists(os.path.join(self.d, "other.jsonl")))

    def test_second_archive_does_not_overwrite(self):
        self.put("cops.jsonl", "a")
        uc.archive_session_files("/w", "cops", stamp=5)
        self.put("cops.jsonl", "b")
        uc.archive_session_files("/w", "cops", stamp=5)
        self.assertEqual(sorted(os.listdir(os.path.join(self.d, "archive"))), ["cops.5.jsonl", "cops.5_1.jsonl"])

    def test_nothing_to_move_and_bad_names(self):
        self.assertEqual(uc.archive_session_files("/w", "cops"), [])
        self.put("x.jsonl")
        self.assertEqual(uc.archive_session_files("/w", "../x"), [])
        self.assertEqual(uc.archive_session_files("/w", ""), [])


class StartFreshTest(unittest.TestCase):
    def run_start(self, cli, fresh, running_kind="none"):
        info = {"state": "active", "cwd": "/w", "cli": cli, "model": "m", "name": "cops"}
        with mock.patch.object(web, "_fleet_status", lambda: {"cops": info}), \
                mock.patch.object(web, "_find_running_for_action", lambda n: (running_kind, [])), \
                mock.patch.object(web, "diag_log", lambda *a, **k: None), \
                mock.patch.object(web, "guard_lock", mock.MagicMock()), \
                mock.patch.object(web, "spawn_session", side_effect=RuntimeError("stop")), \
                mock.patch.object(web.ucli_client, "archive_session_files", return_value=["a"]) as arch:
            try:
                web._start("cops", fresh=fresh, cli=cli)
            except RuntimeError:
                pass
        return arch

    def test_fresh_ucli_archives(self):
        self.run_start("ucli", True).assert_called_once_with("/w", "cops")

    def test_not_fresh_or_not_ucli_or_running_does_not(self):
        self.run_start("ucli", False).assert_not_called()
        self.run_start("claude", True).assert_not_called()
        self.run_start("ucli", True, running_kind="exact").assert_not_called()


class HandoverGateTest(unittest.TestCase):
    def test_ucli_handover_sends_message(self):
        s = NS(name="cops", pid=1, cli="ucli", cwd="/w", sid="cops", model="m", effort="medium")
        sent = []
        with mock.patch.object(web, "_find_running_for_action", lambda n: ("exact", [s])), \
                mock.patch.object(web, "is_tmux_backed", lambda pid: True), \
                mock.patch.object(web, "diag_log", lambda *a, **k: None), \
                mock.patch.object(web, "apply_handover_downgrades", lambda *a, **k: None), \
                mock.patch.object(UcliProvider, "dismiss_stray_dialog", lambda self, n: None, create=True), \
                mock.patch.object(web, "tmux_send_keys", lambda n, t, settle_delay=0.0: sent.append(t) or True):
            res = web._handover("cops")
        self.assertEqual(res, {"ok": True})
        self.assertEqual(len(sent), 1)
        self.assertNotIn("\n", sent[0])        # ucli prepare_input tek satıra indirir


if __name__ == "__main__":
    unittest.main()

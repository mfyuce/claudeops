"""TODO 1005 (gpt-6 R06): _stop/_stop_instance/_retire/_close_project hedefi guard_lock İÇİNDE yeniden çözer; bekleme sırasında
değişen hedefte ESKİ pid öldürülmez, belirsizleşirse hiçbir şey öldürülmez."""
import contextlib
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.commands import web  # noqa: E402


def S(name, pid):
    return NS(name=name, pid=pid)


@contextlib.contextmanager
def _lock(timeout=None):
    yield


class Recheck(unittest.TestCase):
    def run_stop(self, first, second):
        """`first`: kilit öncesi çözüm, `second`: kilit içindeki çözüm. Öldürülen pid'ler döner."""
        seq = [first, second]
        killed = []
        with mock.patch.object(web, "_find_running_for_action", side_effect=lambda *a, **k: seq.pop(0)), \
                mock.patch.object(web, "guard_lock", _lock), \
                mock.patch.object(web, "kill_session_and_parent", side_effect=lambda pid, **k: killed.append(pid) or "ok"), \
                mock.patch.object(web.web_agents, "parent_closed"), mock.patch.object(web, "diag_log"):
            res = web._stop("x")
        return res, killed

    def test_target_changed_during_wait_kills_current_not_stale(self):
        res, killed = self.run_stop(("exact", [S("x", 111)]), ("exact", [S("x", 222)]))
        self.assertEqual(killed, [222])
        self.assertTrue(res["ok"])

    def test_target_gone_kills_nothing(self):
        res, killed = self.run_stop(("exact", [S("x", 111)]), ("none", []))
        self.assertEqual(killed, [])
        self.assertTrue(res["ok"])

    def test_became_ambiguous_kills_nothing(self):
        res, killed = self.run_stop(("exact", [S("x", 111)]), ("ambiguous", [S("x1", 1), S("x2", 2)]))
        self.assertEqual(killed, [])
        self.assertFalse(res["ok"])

    def test_exact_required_but_lost(self):
        seq = [("exact", [S("x", 1)]), ("unique_base", [S("x2", 2)])]
        killed = []
        with mock.patch.object(web, "_find_running_for_action", side_effect=lambda *a, **k: seq.pop(0)), \
                mock.patch.object(web, "guard_lock", _lock), \
                mock.patch.object(web, "kill_session_and_parent", side_effect=lambda pid, **k: killed.append(pid)), \
                mock.patch.object(web.web_agents, "parent_closed"), mock.patch.object(web, "diag_log"):
            res = web._stop("x", exact=True)
        self.assertEqual(killed, [])
        self.assertFalse(res["ok"])

    def test_stop_instance_rechecks(self):
        seq = [("exact", [S("x", 111)]), ("exact", [S("x", 333)])]
        killed = []
        with mock.patch.object(web, "_find_running_for_action", side_effect=lambda *a, **k: seq.pop(0)), \
                mock.patch.object(web, "guard_lock", _lock), \
                mock.patch.object(web, "kill_session_and_parent", side_effect=lambda pid, **k: killed.append(pid)):
            res = web._stop_instance("x")
        self.assertEqual(killed, [333])
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()

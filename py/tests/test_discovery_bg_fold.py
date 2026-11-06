"""Claude Code arka plan oturumu (sessions/<pid>.json `kind:"bg"`) ön yüz satırına katlanır (stdlib unittest).

Hata (TODO 2026-11-06 'hof neden iki adet'): hof'ta ön yüz 707010 (sid 392174a6, `parkedJobId` 43294fa0) + bg 711279
(sid 43294fa0, `jobId` 43294fa0, asıl konuşma) panelde ve `cops list`te iki satır (DUP) görünüyordu. Beklenen: tek satır,
ön yüzün sid'i bg'nin sessionId'si, `bg_pid` işaretli; ebeveynsiz bg KAYBOLMAZ; Durdur bg'yi de kapatır.
Saf/mock: canlı süreç ya da dosya yok."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import discovery as d, kill
from claudeops.session import Session

CWD = "/w/hof"


def front(pid=707010, sid="392174a6", parked="43294fa0", name="hof", cwd=CWD):
    return Session(name=name, pid=pid, cwd=cwd, sid=sid, kind="interactive", parked_job_id=parked)


def bg(pid=711279, sid="43294fa0", job="43294fa0", name="hof", cwd=CWD):
    return Session(name=name, pid=pid, cwd=cwd, sid=sid, kind="bg", job_id=job)


class FoldTests(unittest.TestCase):
    def test_bg_folds_into_front_and_front_reads_bg_sid(self):
        f, b = front(), bg()
        out = d.fold_background([f, b])
        self.assertEqual([s.pid for s in out], [707010])
        self.assertEqual(out[0].sid, "43294fa0")
        self.assertEqual(out[0].bg_pid, 711279)
        self.assertEqual(d.duplicates(out), [])

    def test_order_independent(self):
        out = d.fold_background([bg(), front()])
        self.assertEqual([s.pid for s in out], [707010])

    def test_orphan_bg_is_kept(self):
        b = bg()
        self.assertEqual(d.fold_background([b]), [b])

    def test_other_name_not_folded(self):
        out = d.fold_background([front(name="hof"), bg(name="zz")])
        self.assertEqual(len(out), 2)

    def test_fallback_single_front_same_cwd_without_parked_id(self):
        out = d.fold_background([front(parked=None), bg()])
        self.assertEqual([s.pid for s in out], [707010])

    def test_two_fronts_without_link_is_ambiguous_bg_kept(self):
        out = d.fold_background([front(parked=None), front(pid=1, sid="x", parked=None), bg()])
        self.assertEqual(len(out), 3)

    def test_parked_id_picks_the_right_front(self):
        a, c = front(pid=1, sid="a", parked="other"), front(pid=2, sid="c", parked="43294fa0")
        out = d.fold_background([a, c, bg()])
        self.assertEqual(sorted(s.pid for s in out), [1, 2])
        self.assertEqual(c.bg_pid, 711279)
        self.assertIsNone(a.bg_pid)

    def test_second_bg_stays_visible(self):
        f = front()
        out = d.fold_background([f, bg(), bg(pid=5, sid="zzz", job="43294fa0")])
        self.assertEqual(sorted(s.pid for s in out), [5, 707010])

    def test_non_bg_sessions_untouched(self):
        a, c = front(), front(pid=2, sid="c", parked=None)
        self.assertEqual(d.fold_background([a, c]), [a, c])


class KillBgTests(unittest.TestCase):
    def _run(self, found):
        calls = []
        with mock.patch.object(d, "find_sessions", lambda measure_cpu=True: found), \
                mock.patch.object(kill, "_kill_front_and_parent", lambda pid, grace=1, name=None: calls.append(("front", pid)) or "clean"), \
                mock.patch.object(kill, "kill_session", lambda pid, grace=1, name=None, create_time=None: calls.append(("bg", pid)) or "clean"), \
                mock.patch.object(kill.psutil, "Process", lambda pid: mock.Mock(create_time=lambda: 5.0)):
            res = kill.kill_session_and_parent(707010, grace=1, name="hof")
        return res, calls

    def test_stop_kills_folded_bg_after_front(self):
        f = front(); f.bg_pid = 711279
        res, calls = self._run([f])
        self.assertEqual(res, "clean")
        self.assertEqual(calls, [("front", 707010), ("bg", 711279)])

    def test_stop_without_bg_kills_only_front(self):
        res, calls = self._run([front()])
        self.assertEqual(calls, [("front", 707010)])


if __name__ == "__main__":
    unittest.main()

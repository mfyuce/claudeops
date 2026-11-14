import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import turns  # noqa: E402


class Prov:
    def __init__(self, seq):
        self.seq = list(seq)

    def busy_status_pattern(self):
        return None            # codex/agy stratejisi: stable_polls ardışık aynı

    def last_exchange(self, cwd, sid):
        return self.seq.pop(0) if self.seq else self.last

    def discover_live_sid(self, *a):
        return None


class TransientNoneTest(unittest.TestCase):
    S = SimpleNamespace(name="x", cwd="/w", sid="s")

    def test_single_unreadable_poll_does_not_end_wait(self):
        done = {"assistant": "bitti"}
        p = Prov([None, done, done, done])
        p.last = done
        with mock.patch.object(turns.time, "sleep"):
            self.assertEqual(turns.wait_for_reply(self.S, p, {"assistant": "eski"}, timeout=30, poll=0, stable_polls=2), "bitti")

    def test_persistent_none_gives_up(self):
        p = Prov([None] * 10)
        p.last = None
        with mock.patch.object(turns.time, "sleep"):
            self.assertIsNone(turns.wait_for_reply(self.S, p, {"assistant": "eski"}, timeout=30, poll=0))


if __name__ == "__main__":
    unittest.main()

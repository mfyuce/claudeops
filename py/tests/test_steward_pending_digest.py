"""D4: bekleyen sahip soruları için günde 2 kez TEK ntfy özeti. Saf kararlar + uygulama (gerçek ntfy/dosya YOK)."""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import steward as sw  # noqa: E402
from claudeops.commands import web_steward as ws  # noqa: E402
from test_steward_engine_multi import _Engine  # noqa: E402


def at(h, day=10):
    return time.mktime((2026, 11, day, h, 0, 0, 0, 0, -1))


def q(project="p", age_h=5.0, routine=False, notified=0.0, status="open", now=None):
    now = now if now is not None else at(12)
    return sw.Question(id="x", project=project, text="t", created_at=now - age_h * 3600, status=status, routine=routine,
                       notified_at=notified)


class SlotTest(unittest.TestCase):
    def test_slots(self):
        self.assertEqual(sw.pending_digest_slot(at(8)), "")
        self.assertEqual(sw.pending_digest_slot(at(9)), "2026-11-10@09")
        self.assertEqual(sw.pending_digest_slot(at(17)), "2026-11-10@09")
        self.assertEqual(sw.pending_digest_slot(at(18)), "2026-11-10@18")
        self.assertEqual(sw.pending_digest_slot(at(23)), "2026-11-10@18")


class TextTest(unittest.TestCase):
    def test_empty_when_nothing_open(self):
        self.assertEqual(sw.pending_digest_text([], at(12)), "")
        self.assertEqual(sw.pending_digest_text([q(routine=True), q(status="answered")], at(12)), "")

    def test_counts_oldest_and_unnotified(self):
        qs = [q("a", 58.0), q("a", 2.0, notified=1.0), q("b", 10.0)]
        t = sw.pending_digest_text(qs, at(12))
        self.assertIn("3 soru", t)
        self.assertIn("58 sa", t)
        self.assertIn("2 tanesi telefona hiç gitmedi", t)
        self.assertIn("a:2", t)
        self.assertIn("3 owner question", sw.pending_digest_text(qs, at(12), "en"))


class ApplyTest(_Engine):
    def test_once_per_slot_and_skipped_without_questions(self):
        cfg = sw.Config(enabled=True)
        sent = []
        with mock.patch.object(ws, "_notify", lambda c, text, click="": sent.append(text) or True):
            self.assertFalse(ws.maybe_pending_digest(cfg, at(8)))                 # dilim yok
            self.assertFalse(ws.maybe_pending_digest(cfg, at(9)))                 # soru yok: gönderilmez
            sw.add_question("p", "Bir soru?", source="t")
            self.assertFalse(ws.maybe_pending_digest(cfg, at(10)))                # aynı dilim zaten işaretli
            self.assertTrue(ws.maybe_pending_digest(cfg, at(18)))                 # yeni dilim: gider
            self.assertFalse(ws.maybe_pending_digest(cfg, at(19)))                # bir kez
        self.assertEqual(len(sent), 1)
        self.assertIn("1 soru", sent[0])


if __name__ == "__main__":
    unittest.main()

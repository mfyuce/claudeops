"""rs/prov: bozuk onay kartı açılıştaki kurtarmayı düşürmez ve bloklamaz (yalnız geçici dizin)."""
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_approval as ua  # noqa: E402


class BadCards(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(prefix="cops-appr-card-")
        self.addCleanup(d.cleanup)
        p = mock.patch.object(ua, "ROOT", os.path.join(d.name, "ucli_approval"))
        p.start()
        self.addCleanup(p.stop)
        ua.register("r1", "/w", "", ["x"])
        ua.set_state("r1", "suspended")
        self.pdir = os.path.join(ua.dir_for("r1"), "pending")
        with open(os.path.join(self.pdir, "b.json"), "w") as f:
            json.dump({"id": "b", "status": "pending"}, f)

    def test_deeply_nested_card_is_skipped(self):
        with open(os.path.join(self.pdir, "a.json"), "wb") as f:
            f.write(b"[" * 100000)
        self.assertEqual([p["id"] for p in ua.pending("r1")], ["b"])
        self.assertEqual(ua.recover_resuming(), 0)

    def test_fifo_card_does_not_block(self):
        fifo = os.path.join(self.pdir, "a.json")
        os.mkfifo(fifo)
        got = []
        t = threading.Thread(target=lambda: got.append((ua.recover_resuming(), [p["id"] for p in ua.pending("r1")])),
                             daemon=True)
        t.start()
        t.join(5)
        blocked = t.is_alive()
        if blocked:
            os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
        self.assertFalse(blocked)
        self.assertEqual(got, [(0, ["b"])])


if __name__ == "__main__":
    unittest.main()

"""`bg_work.session_record_shell_since` (main `220007a9`, TBD#442 a) rs-prov kural eşliği: süreç kaydı `session_record_status`
gibi okunur. (1) `.json` adlı FIFO açılışta bloklamaz (değnekçi turu asılırdı); (2) yalnız CANLI sürecin (pid + procStart
eşleşen) kaydı sayılır: ölü süreçten kalan daha yeni damgalı `shell` kaydı 30 dk'lık eşiği sıfırlamaz. Yalnız geçici dizin."""
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import bg_work  # noqa: E402


def _mine():
    with open(f"/proc/{os.getpid()}/stat") as f:
        return f.read().rsplit(")", 1)[1].split()[19]


class ShellSinceReadsLiveRecordsOnly(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        self.now = 10_000_000.0

    def rec(self, fname, at_s, proc_start=None, status="shell"):
        d = {"pid": os.getpid(), "sessionId": "s1", "status": status, "procStart": proc_start or _mine(),
             "statusUpdatedAt": at_s * 1000}
        with open(os.path.join(self.dir, fname), "w") as f:
            json.dump(d, f)

    def call(self):
        out = []
        t = threading.Thread(target=lambda: out.append(bg_work.session_record_shell_since(self.dir, "s1")), daemon=True)
        t.start()
        t.join(5)
        self.assertFalse(t.is_alive(), "FIFO kaydında bloklandı")
        return out[0]

    def test_fifo_named_json_does_not_block(self):
        self.rec("1.json", self.now - 1801)
        os.mkfifo(os.path.join(self.dir, "2.json"))
        self.assertEqual(self.call(), self.now - 1801)

    def test_dead_process_record_does_not_reset_the_age(self):
        self.rec("1.json", self.now - 1801)
        self.rec("2.json", self.now - 10, proc_start="1")      # aynı pid, başka başlangıç: ölü süreç
        self.assertEqual(self.call(), self.now - 1801)
        self.assertTrue(bg_work.shell_only_stale(self.dir, "s1", self.now))


if __name__ == "__main__":
    unittest.main()

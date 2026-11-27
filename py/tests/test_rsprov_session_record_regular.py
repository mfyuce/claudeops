"""`sessions/<pid>.json` okuyucuları yalnız normal ve 1 MiB'ı aşmayan dosya okur (kardeşi `bg_work`, `d9ce526f`): FIFO
açılışta süresiz bekletiyordu. Testin kendi süreci dışında süreç ve gerçek oturum dizini YOK."""
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import owner_dialog  # noqa: E402
from claudeops.paths import proc_stat_fields  # noqa: E402
from claudeops.providers import claude_provider as cp  # noqa: E402

PID = os.getpid()


class SessionRecordReaders(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        self.path = os.path.join(d.name, f"{PID}.json")
        p = mock.patch.object(cp, "SESSIONS_DIR", d.name)
        p.start()
        self.addCleanup(p.stop)

    def readers(self):
        return (("kayit", lambda: cp._session_record(PID), None),
                ("bekleme", lambda: owner_dialog.session_waiting_for(self.dir, PID), ""))

    def write(self, pad=0):
        doc = {"pid": PID, "sessionId": "s", "procStart": proc_stat_fields(PID)[19], "status": "waiting",
               "waitingFor": "input needed", "pad": "x" * pad}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def test_regular_record_is_still_read(self):
        self.write()
        self.assertEqual([read() for _, read, _ in self.readers()], [("s", None), "input needed"])

    def test_oversized_record_is_ignored(self):
        self.write(pad=1024 * 1024)
        for name, read, empty in self.readers():
            with self.subTest(name):
                self.assertEqual(read(), empty)

    def test_fifo_does_not_block(self):
        os.mkfifo(self.path)
        for name, read, empty in self.readers():
            with self.subTest(name):
                got = []
                t = threading.Thread(target=lambda: got.append(read()), daemon=True)
                t.start()
                t.join(5)
                blocked = t.is_alive()
                if blocked:      # okuyucuyu serbest bırak: yazıcı açılıp kapanınca EOF
                    os.close(os.open(self.path, os.O_WRONLY | os.O_NONBLOCK))
                    t.join(5)
                self.assertFalse(blocked, "FIFO okuması bloklandı")
                self.assertEqual(got, [empty])


if __name__ == "__main__":
    unittest.main()

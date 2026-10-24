"""hosts.json oku-değiştir-yaz döngüsü kilitli: eşzamanlı save_host/promote_base_url/remove_host birbirinin yazısını ezmez."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import hosts  # noqa: E402


class ConcurrentWriteTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = mock.patch.object(hosts, "HOSTS_JSON", os.path.join(self.d, "hosts.json"))
        p.start()
        self.addCleanup(p.stop)

    def test_parallel_saves_all_survive(self):
        n = 24
        errs = []

        def add(i):
            try:
                self.assertTrue(hosts.save_host(f"h{i}", f"http://h{i}", "tok")["ok"])
            except Exception as e:      # noqa: BLE001
                errs.append(e)
        ths = [threading.Thread(target=add, args=(i,)) for i in range(n)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(errs, [])
        self.assertEqual(sorted(h["name"] for h in hosts.load_hosts()), sorted(f"h{i}" for i in range(n)))

    def test_flock_failure_falls_back_to_thread_lock(self):
        with mock.patch.object(hosts.fcntl, "flock", side_effect=OSError("no")):
            self.assertTrue(hosts.save_host("x", "http://x", "t")["ok"])


if __name__ == "__main__":
    unittest.main()

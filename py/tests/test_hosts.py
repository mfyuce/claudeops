"""hosts.json oku-değiştir-yaz döngüsü kilitli: eşzamanlı save_host/promote_base_url/remove_host birbirinin yazısını ezmez."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import atomic_json, hosts  # noqa: E402


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
        with mock.patch.object(atomic_json.fcntl, "flock", side_effect=OSError("no")):
            self.assertTrue(hosts.save_host("x", "http://x", "t")["ok"])


if __name__ == "__main__":
    unittest.main()


class ReachLoopbackTest(unittest.TestCase):
    """menzil reach dinleyicisi (127.0.0.1:187xx) YALNIZ extra_urls'ta serbest; başka loopback hâlâ SSRF olarak reddedilir."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = mock.patch.object(hosts, "HOSTS_JSON", os.path.join(self.d, "hosts.json"))
        p.start()
        self.addCleanup(p.stop)

    def save(self, base, extra):
        return hosts.save_host("h1", base, "tok", extra_urls=extra)

    def test_reach_port_loopback_ok_in_extra_urls(self):
        r = self.save("https://example.invalid", "http://127.0.0.1:18766")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual([h["extra_urls"] for h in hosts.load_hosts()], [["http://127.0.0.1:18766"]])

    def test_everything_else_still_blocked(self):
        for base, extra in (("http://127.0.0.1:18766", ""),                     # base_url'e istisna YOK
                            ("https://example.invalid", "http://127.0.0.1:8765"),   # panelin kendi portu
                            ("https://example.invalid", "http://127.0.0.1:18800"),
                            ("https://example.invalid", "https://127.0.0.1:18766"),
                            ("https://example.invalid", "http://localhost:18766"),  # DNS adı istisna değil
                            ("https://example.invalid", "http://169.254.169.254:18766")):
            self.assertFalse(self.save(base, extra).get("ok"), (base, extra))

    def test_helper(self):
        self.assertTrue(hosts._is_reach_loopback("http://[::1]:18700"))
        self.assertFalse(hosts._is_reach_loopback("http://127.0.0.1"))


class DbModeIrregularTest(unittest.TestCase):
    """db kipinde düzensiz-kayıt denetimi DB değerine bakar (dosya bayat), yedek DB dökümüdür."""

    def test_irregular_detected_from_db_not_stale_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hosts.json")
            with open(path, "w") as f:
                f.write('[{"name": "a"}]')   # bayat ve temiz dosya
            from claudeops import statedocs
            with mock.patch.object(hosts, "HOSTS_JSON", path), \
                 mock.patch.object(statedocs, "backend", return_value="db"), \
                 mock.patch.object(statedocs, "_db_ok", return_value=True), \
                 mock.patch.object(statedocs, "read_json", return_value=[{"name": "a"}, "junk"]):
                self.assertTrue(hosts._has_irregular_entries())
                hosts._backup_corrupt()
                self.assertTrue(any(n.startswith("hosts.json.corrupt-") for n in os.listdir(d)))


if __name__ == "__main__" and False:
    pass

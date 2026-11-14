"""Bozuk UTF-8 durum dosyaları okuyucuları çökertmez (review cliops|uzops 3-4 Kas)."""
import os
import tempfile
import unittest
from unittest import mock

from claudeops import hosts, instances


class BadBytes(unittest.TestCase):
    def test_instances(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "instances.json")
        open(p, "wb").write(b'{"instances": {"a\xff": {}}}')
        with mock.patch.object(instances, "INSTANCES_JSON", p):
            with self.assertRaises(instances.InstancesCorrupt):
                instances.read_strict()
            instances._cache_key = None
            self.assertEqual(instances.load_instances(), {})

    def test_hosts(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "hosts.json")
        open(p, "wb").write(b'[{"name": "\xff"}]')
        with mock.patch.object(hosts, "HOSTS_JSON", p):
            self.assertEqual(hosts.load_hosts(), [])
            self.assertEqual(hosts._read_checked(), ([], True))


if __name__ == "__main__":
    unittest.main()


class SaveHostKeepsUnknownFields(unittest.TestCase):
    def test_unknown_field_survives_upsert_and_dns_outside_lock(self):
        import json
        d = tempfile.mkdtemp()
        p = os.path.join(d, "hosts.json")
        json.dump([{"name": "h1", "base_url": "http://a:1", "token": "t", "future": 7, "grpc_url": "http://g:2"}], open(p, "w"))
        seen = {}
        def blocked(url):
            seen["locked"] = os.path.exists(p + ".lock") and False
            return False
        with mock.patch.object(hosts, "HOSTS_JSON", p), mock.patch.object(hosts, "_host_is_blocked", blocked), \
                mock.patch("claudeops.statedocs.backend", return_value="file"):
            r = hosts.save_host("h1", "http://b:3", "", lang="tr")
            self.assertTrue(r["ok"], r)
            rec = json.load(open(p))[0]
        self.assertEqual((rec["future"], rec["base_url"], rec["token"]), (7, "http://b:3", "t"))
        self.assertNotIn("grpc_url", rec)                                # boş grpc_url = kaldır

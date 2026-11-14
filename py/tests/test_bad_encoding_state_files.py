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

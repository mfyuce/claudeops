"""hosts.json bozuk/okunamıyorsa yazma REDDEDİLİR (yedek alınır): sonraki save/remove/promote tüm host+token kayıtlarını silmesin."""
import glob
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import hosts  # noqa: E402


class CorruptHostsTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.f = os.path.join(self.d, "hosts.json")
        p = mock.patch.object(hosts, "HOSTS_JSON", self.f)
        p.start()
        self.addCleanup(p.stop)

    def put(self, text):
        with open(self.f, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_save_refused_on_corrupt_and_backup_kept(self):
        self.put('[{"name": "a", "base_url": "http://x", "token": "SEKRET"}')   # kesik JSON
        r = hosts.save_host("b", "http://y", "tok")
        self.assertFalse(r["ok"])
        self.assertIn("SEKRET", open(self.f).read())                             # dosya olduğu gibi
        bk = glob.glob(self.f + ".corrupt-*")
        self.assertEqual(len(bk), 1)
        self.assertIn("SEKRET", open(bk[0]).read())
        self.assertEqual(os.stat(bk[0]).st_mode & 0o777, 0o600)
        hosts.save_host("b", "http://y", "tok")                                  # tekrar: yedek çoğalmaz
        self.assertEqual(len(glob.glob(self.f + ".corrupt-*")), 1)

    def test_remove_and_promote_refused_on_corrupt(self):
        self.put("{not json")
        self.assertFalse(hosts.remove_host("a")["ok"])
        hosts.promote_base_url("a", "http://z")                                  # sessiz no-op, yazmaz
        self.assertEqual(open(self.f).read(), "{not json")

    def test_non_list_json_is_corrupt(self):
        self.put('{"name": "a"}')
        self.assertFalse(hosts.save_host("b", "http://y", "tok")["ok"])
        self.assertEqual(open(self.f).read(), '{"name": "a"}')

    def test_missing_or_empty_file_still_writable(self):
        self.assertTrue(hosts.save_host("b", "http://y", "tok")["ok"])           # dosya yok
        os.remove(self.f)
        self.put("  \n")                                                         # boş dosya kaybedecek veri yok
        self.assertTrue(hosts.save_host("c", "http://y", "tok")["ok"])
        self.assertEqual([h["name"] for h in hosts.load_hosts()], ["c"])

    def test_healthy_roundtrip_unchanged(self):
        hosts.save_host("a", "http://x", "t1")
        hosts.save_host("b", "http://y", "t2")
        self.assertTrue(hosts.remove_host("a")["ok"])
        self.assertEqual([h["name"] for h in hosts.load_hosts()], ["b"])
        self.assertEqual(glob.glob(self.f + ".corrupt-*"), [])


if __name__ == "__main__":
    unittest.main()

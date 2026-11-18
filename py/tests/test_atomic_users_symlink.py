"""Atomik yazım yardımcısına taşınan yerler: routing symlink'i düz dosyayla DEĞİŞTİRMEZ (asıl hedefe yazar, izin korunur),
ucli_agents token dosyası 0600 + atomik (review cliops R-6/R-8/R-9, 17 Kas)."""
import os
import stat
import tempfile
import unittest
from unittest import mock

from claudeops import routing, ucli_agents


class RoutingSymlink(unittest.TestCase):
    def test_symlink_kept_and_target_written_with_mode(self):
        d = tempfile.mkdtemp()
        real = os.path.join(d, "real_AGENTS.md")
        link = os.path.join(d, "AGENTS.md")
        open(real, "w").write("kullanıcı metni\n")
        os.chmod(real, 0o640)
        os.symlink(real, link)
        with mock.patch.object(routing, "routing_text", lambda: "YÖNERGE"), mock.patch.object(routing, "routing_guidance_enabled", lambda: True):
            self.assertEqual(routing._sync_one(link, create=False), "written")
        self.assertTrue(os.path.islink(link))                                   # symlink düz dosyaya dönmedi
        self.assertIn("kullanıcı metni", open(real).read())
        self.assertIn("YÖNERGE", open(real).read())
        self.assertEqual(stat.S_IMODE(os.stat(real).st_mode), 0o640)            # izin düşmedi
        self.assertEqual([f for f in os.listdir(d) if ".tmp" in f], [])         # tmp sızmadı


class TokenFile(unittest.TestCase):
    def test_token_file_0600_atomic(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(ucli_agents, "TOKEN_DIR", d):
            p = ucli_agents._write_token_file("sess_1", "tok123")
            self.assertEqual(open(p).read(), "tok123")
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
            ucli_agents._write_token_file("sess_1", "tok456")
            self.assertEqual(open(p).read(), "tok456")
        self.assertEqual([f for f in os.listdir(d) if f.endswith(".tmp")], [])

class OrphanMarker(unittest.TestCase):
    def test_orphan_begin_does_not_eat_user_text(self):
        orphan = f"önce\n{routing.BLOCK_BEGIN}\nkullanıcının kendi notu\n"
        a = routing._with_block(orphan, "YÖNERGE")
        b = routing._with_block(a, "YÖNERGE2")          # ikinci eşitleme: eskiden ilk BEGIN'den END'e kadar her şeyi siliyordu
        self.assertIn("kullanıcının kendi notu", b)
        self.assertIn("YÖNERGE2", b)
        self.assertNotIn("YÖNERGE\n", b.replace("YÖNERGE2", ""))
        self.assertEqual(b.count(routing.BLOCK_END), 1)

    def test_normal_block_replaced_and_removed(self):
        x = routing._with_block("a\n", "ILK")
        y = routing._with_block(x, "IKINCI")
        self.assertIn("IKINCI", y); self.assertNotIn("ILK", y)
        self.assertEqual(routing._with_block(y, None).strip(), "a")


if __name__ == "__main__":
    unittest.main()

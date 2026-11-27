"""rs/prov G9: spawn yürütme ve yönerge eşitlemesindeki Python hataları. Yalnız geçici dizin; ayarlar, günlük, süreç ve
tmux sahte (gerçek durum dizinine, ağa ve canlı sürece dokunulmaz)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import routing  # noqa: E402


class BrokenBackupLinkTest(unittest.TestCase):
    """`.bak-routing` hedefsiz bağlantıysa `copy2` onu izleyip dizin dışına yazıyordu."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = os.path.join(d.name, "ev")
        os.mkdir(self.dir)
        self.outside = os.path.join(d.name, "disarisi.md")
        self.logs = []
        for p in (mock.patch.object(routing, "load_settings", lambda: {"routing_guidance_text": "yonerge"}),
                  mock.patch.object(routing, "routing_guidance_enabled", lambda: True),
                  mock.patch.object(routing, "diag_log", lambda ev, **k: self.logs.append((ev, k)))):
            p.start()
            self.addCleanup(p.stop)

    def _file(self, name, text="kullanici\n"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _refused(self, target):
        codex = self._file("AGENTS.md")
        bak = codex + ".bak-routing"
        os.symlink(target, bak)
        agy = os.path.join(self.dir, "GEMINI.md")
        res = routing.sync_global_files(codex_path=codex, agy_path=agy)
        self.assertEqual(res, {"codex": "skipped:broken backup link", "agy": "written"})
        self.assertEqual(self._read(codex), "kullanici\n")
        self.assertEqual(os.readlink(bak), target)
        self.assertEqual(self.logs, [("routing_guidance_backup_broken_link", {"path": codex, "backup": bak})])

    def test_dangling_link_writes_neither_backup_nor_target(self):
        self._refused(self.outside)
        self.assertFalse(os.path.exists(self.outside))

    def test_link_loop_is_refused_too(self):
        self._refused("AGENTS.md.bak-routing")

    def test_existing_agy_file_with_dangling_backup_link_is_untouched(self):
        agy = self._file("GEMINI.md")
        os.symlink(self.outside, agy + ".bak-routing")
        res = routing.sync_global_files(codex_path=os.path.join(self.dir, "yok.md"), agy_path=agy)
        self.assertEqual(res["agy"], "skipped:broken backup link")
        self.assertEqual(self._read(agy), "kullanici\n")
        self.assertFalse(os.path.exists(self.outside))

    def test_link_to_an_existing_file_still_counts_as_a_backup(self):
        codex = self._file("AGENTS.md")
        old = self._file("eski-yedek", "eski\n")
        os.symlink(old, codex + ".bak-routing")
        res = routing.sync_global_files(codex_path=codex, agy_path=os.path.join(self.dir, "GEMINI.md"))
        self.assertEqual(res["codex"], "written")
        self.assertEqual(self._read(old), "eski\n")
        self.assertIn("yonerge", self._read(codex))
        self.assertEqual(self.logs, [])


if __name__ == "__main__":
    unittest.main()

"""tmux'ta hedeflenemeyen adda kabuk parçası ValueError verir; spawn bunu yakalar: istisna çıkmaz, hiçbir pencere ya da
yedek izleyici başlatılmaz, günlüğe düşer."""
import tempfile
import unittest
from unittest import mock

from claudeops import spawn


class BadNameSpawnTests(unittest.TestCase):
    def test_bad_name_returns_without_launching_anything(self):
        events, launched = [], []
        with tempfile.TemporaryDirectory() as cwd, \
                mock.patch.object(spawn, "tmux_available", lambda: True), \
                mock.patch.object(spawn, "_reclaim_ghost_session", lambda *a: None), \
                mock.patch.object(spawn.shutil, "which", lambda n: "/usr/bin/" + n), \
                mock.patch.object(spawn, "_launch_gnome_terminal", lambda *a: launched.append(a) or True), \
                mock.patch.object(spawn.threading, "Thread", side_effect=AssertionError("izleyici başlamamalı")), \
                mock.patch.object(spawn, "diag_log", lambda ev, **kw: events.append(ev)):
            kind = spawn.spawn_session(name="a#(touch x)", cwd=cwd, model="", cli="shell", display=":0",
                                       force_new=True)
        self.assertEqual(kind, "new")
        self.assertEqual(launched, [])
        self.assertIn("spawn_bad_name", events)


if __name__ == "__main__":
    unittest.main()

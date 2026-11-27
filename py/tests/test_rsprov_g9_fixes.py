"""rs/prov G9: spawn yürütme ve yönerge eşitlemesindeki Python hataları. Yalnız geçici dizin; ayarlar, günlük, süreç ve
tmux sahte (gerçek durum dizinine, ağa ve canlı sürece dokunulmaz)."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import authz, routing, spawn, tmux_backend as tb  # noqa: E402


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


class GhostScreenNotLoggedTest(unittest.TestCase):
    """Hayaletin son ekranı (sır taşıyabilir) diag.log'a düz yazılıyordu."""

    def _reclaim(self, screen):
        logs = []
        with mock.patch.object(spawn, "tmux_available", lambda: True), \
                mock.patch.object(tb, "tmux_ghost_session", lambda n: True), \
                mock.patch.object(tb, "tmux_capture", lambda n, lines=2000: screen), \
                mock.patch.object(tb, "tmux_kill_session", lambda n: None), \
                mock.patch.object(spawn, "diag_log", lambda ev, **k: logs.append((ev, k))):
            spawn._reclaim_ghost_session("p", "claude")
        return logs

    def test_only_counts_reach_the_log(self):
        screen = "\x1b[31mexport API_KEY=sk-cok-gizli\x1b[0m\n\n   \n" + "ğ" * 2000 + "\n"
        logs = self._reclaim(screen)
        self.assertEqual(logs, [("spawn_ghost_reclaimed",
                                 {"name": "p", "cli": "claude", "screen_lines": 2, "screen_chars": len("export API_KEY=sk-cok-gizli") + 1 + 2000})])

    def test_unreadable_screen_counts_zero(self):
        self.assertEqual(self._reclaim(None)[0][1], {"name": "p", "cli": "claude", "screen_lines": 0, "screen_chars": 0})


def _spawn(gnome_terminal=True, tmux=True, **kw):
    """`spawn_session`, her dış sınır sahte: (dönüş, günlük, açılan şeyler)."""
    logs, opened = [], []
    provider = mock.Mock(accepts_cli_opts=False, mcp_needs_cwd=False)
    provider.resolve_effort.return_value = "high"
    provider.env_overrides.return_value = {}
    provider.build_inner_command.return_value = "sahte-cli"
    which = SimpleNamespace(which=lambda n: "/usr/bin/gnome-terminal" if gnome_terminal else None)
    with mock.patch.object(spawn, "get_provider", lambda cli: provider), \
            mock.patch.object(authz, "spawn_env", lambda *a: {}), \
            mock.patch.object(spawn, "spawn_priority_prefix", lambda n: ""), \
            mock.patch.object(spawn, "_reclaim_ghost_session", lambda n, c: None), \
            mock.patch.object(spawn, "tmux_available", lambda: tmux), \
            mock.patch.object(spawn, "tmux_spawn_direct", lambda *a: opened.append("tmux") or True), \
            mock.patch.object(spawn, "_launch_gnome_terminal", lambda *a: opened.append("pencere") or True), \
            mock.patch.object(spawn, "shutil", which), \
            mock.patch.object(spawn, "diag_log", lambda ev, **k: logs.append((ev, k))):
        ret = spawn.spawn_session("p", "/w", "m", display=":9", effort="high", force_new=True, cli="x", **kw)
    return ret, logs, opened


class HiddenWithoutTmuxTest(unittest.TestCase):
    """Gizli başlatmada tmux yoksa hiçbir şey açılmıyor ve iz kalmıyordu."""

    def test_is_logged_and_nothing_is_opened(self):
        ret, logs, opened = _spawn(tmux=False, hidden=True)
        self.assertEqual((ret, opened), ("new", []))
        self.assertEqual(logs, [("spawn_hidden_no_tmux", {"name": "p", "cwd": "/w"})])

    def test_hidden_with_tmux_is_unchanged(self):
        _, logs, opened = _spawn(hidden=True)
        self.assertEqual(opened, ["tmux"])
        self.assertEqual([e for e, _ in logs], ["spawn_hidden"])

    def test_missing_terminal_keeps_its_single_event(self):
        for hidden in (False, True):
            _, logs, opened = _spawn(gnome_terminal=False, tmux=False, hidden=hidden)
            self.assertEqual(opened, [])
            self.assertEqual([e for e, _ in logs], ["spawn_no_gnome_terminal"])


class WatchdogValueErrorTest(unittest.TestCase):
    """Bekçide `Popen` `ValueError`ı iş parçacığını iz bırakmadan öldürüyordu."""

    def test_is_logged_without_the_message_and_ends_the_watchdog(self):
        logs, direct, clock = [], [], [0.0]

        def launch(*a):
            raise ValueError("illegal environment variable name: API_KEY=sk-cok-gizli")

        def sleep(s):
            clock[0] += s

        with mock.patch.object(spawn, "tmux_has_session", lambda n: False), \
                mock.patch.object(spawn, "tmux_spawn_direct", lambda *a: direct.append(a) or True), \
                mock.patch.object(spawn, "_launch_gnome_terminal", launch), \
                mock.patch.object(spawn, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)), \
                mock.patch.object(spawn, "diag_log", lambda ev, **k: logs.append((ev, k))):
            spawn._fallback_watchdog("p", "/w", "inner", {"API_KEY": "sk-cok-gizli"}, "cmd")
        self.assertEqual(direct, [])
        self.assertEqual(logs, [
            ("spawn_retry", {"name": "p", "cwd": "/w", "attempt": 1}),
            ("spawn_retry_launch_error", {"name": "p", "cwd": "/w", "attempt": 1, "error": "ValueError"})])


if __name__ == "__main__":
    unittest.main()

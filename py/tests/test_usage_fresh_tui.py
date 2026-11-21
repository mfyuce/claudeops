"""copilot oturumsuz kullanım (TUI yolu): ayrıştırma (canlı ekran fikstürü) + TTL önbelleği. Gerçek tmux/copilot YOK."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops.commands import web  # noqa: E402
from claudeops.providers.copilot_provider import CopilotProvider  # noqa: E402

SCREEN = """   Active account/provider usage
   Plan       ■■■■■■■■■■■■■■■■■■■■ 35% used • resets in 11 days
              530 / 1,500 AIC
 /tmp
"""


class P(unittest.TestCase):
    def test_parse_percent_fraction_reset(self):
        e = CopilotProvider().parse_fresh_usage(SCREEN)
        self.assertEqual(e, [{"label": "Plan (AI Credits)", "percent": "35", "detail": "530 / 1,500 AIC · resets in 11 days"}])

    def test_parse_without_reset_unchanged(self):
        e = CopilotProvider().parse_usage_text("Plan   ■■ 10% used\n 5 / 100 AIC\n")
        self.assertEqual(e[0]["detail"], "5 / 100 AIC")

    def test_argv_and_no_print_mode(self):
        a = CopilotProvider().usage_fresh_tui_argv()
        self.assertEqual(len(a), 1)
        self.assertNotIn("-p", a)


class Ttl(unittest.TestCase):
    def setUp(self):
        web._USAGE_TUI_CACHE.clear()
        self.p = CopilotProvider()

    def test_ttl_cache_and_stale(self):
        ok = {"available": True, "entries": [1]}
        with mock.patch.object(web, "_usage_fresh_tui_run", side_effect=[ok, None, None]) as m:
            self.assertEqual(web._usage_fresh_tui(self.p, now=1000.0), ok)
            self.assertEqual(web._usage_fresh_tui(self.p, now=1100.0), ok)      # vade dolmadı: yeniden okunmaz
            self.assertEqual(m.call_count, 1)
            r = web._usage_fresh_tui(self.p, now=1000.0 + web._USAGE_TUI_TTL + 1)   # başarısız: son iyi değer, işaretli
            self.assertTrue(r["stale_read"])
            self.assertIsNone(web._usage_fresh_tui(self.p, now=1000.0 + 3 * web._USAGE_TUI_TTL))


class IsolatedNoRealRead(unittest.TestCase):
    def test_isolated_panel_does_not_launch_real_cli(self):
        self.assertTrue(web._isolated_state())      # test koşucusu geçici CLAUDEOPS_DIR kullanır
        with mock.patch("subprocess.run", side_effect=AssertionError("gerçek tmux/CLI açılmamalı")):
            self.assertIsNone(web._usage_fresh_tui_run(CopilotProvider()))

    def test_default_dir_is_not_isolated(self):
        from claudeops import paths
        with mock.patch.object(paths, "CLAUDEOPS_DIR", os.path.join(paths.CLAUDE_DIR, "claudeops")):
            self.assertFalse(web._isolated_state())


class Sweep(unittest.TestCase):
    """Yetim `cops-usage-*` tmux sunucuları (panel okuma ortasında öldürülünce `finally` çalışmaz): kapat + soket dosyasını sil."""

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        self.calls = []
        p = mock.patch("subprocess.run", lambda argv, **k: self.calls.append(argv))
        p.start()
        self.addCleanup(p.stop)

    def sock(self, name, age=0.0):
        path = os.path.join(self.d, name)
        open(path, "w").close()
        t = 1_000_000.0 - age
        os.utime(path, (t, t))
        return path

    def sweep(self):
        return web.usage_tui_sweep(now=1_000_000.0, sock_dir=self.d)

    def test_dead_pid_socket_closed_and_unlinked(self):
        path = self.sock("cops-usage-copilot-999999999")       # var olmayan pid
        self.assertEqual(self.sweep(), 1)
        self.assertFalse(os.path.exists(path))
        self.assertIn(["tmux", "-L", "cops-usage-copilot-999999999", "kill-server"], self.calls)

    def test_own_fresh_socket_untouched_but_own_old_one_closed(self):
        mine = f"cops-usage-copilot-{os.getpid()}"
        path = self.sock(mine, age=5)
        self.assertEqual(self.sweep(), 0)
        self.assertTrue(os.path.exists(path))
        os.utime(path, (1_000_000.0 - 3600, 1_000_000.0 - 3600))       # 1 saat: takılmış okuma
        self.assertEqual(self.sweep(), 1)
        self.assertFalse(os.path.exists(path))

    def test_live_other_pid_fresh_untouched_old_closed(self):
        name = f"cops-usage-copilot-{os.getppid()}"         # yaşayan başka süreç
        path = self.sock(name, age=30)
        self.assertEqual(self.sweep(), 0)
        os.utime(path, (1_000_000.0 - 3600, 1_000_000.0 - 3600))
        self.assertEqual(self.sweep(), 1)

    def test_other_sockets_ignored_and_missing_dir_ok(self):
        keep = self.sock("cops", age=99999)
        self.assertEqual(self.sweep(), 0)
        self.assertTrue(os.path.exists(keep))
        self.assertEqual(web.usage_tui_sweep(now=1.0, sock_dir=os.path.join(self.d, "yok")), 0)


if __name__ == "__main__":
    unittest.main()

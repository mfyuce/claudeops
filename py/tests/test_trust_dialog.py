"""Güven diyaloğu (2026-11-02 dersi): tanı, YALNIZ kayıtlıda Yes, erken ölüm = 'başlatma başarısız'. Çalıştırma: python3 tests/test_trust_dialog.py"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import trust_dialog as td  # noqa: E402
from claudeops.commands import web  # noqa: E402

DIALOG = ("Accessing workspace:\n /home/x/zlkrnbulent\n\n Is this a project you created or one you trust?\n\n"
          " ❯ 1. Yes, I trust this folder\n   2. No, exit\n")
DIALOG_NO_PTR = DIALOG.replace("❯ 1.", "  1.").replace("   2.", " ❯ 2.")


def run(text, registered=True, alive=None):
    keys, raws, logs = [], [], []
    r = td.handle("n", registered, capture=lambda n: text, send_key=lambda n, k: keys.append(k) or True,
                  send_raw=lambda n, d: raws.append(d) or True, strip=lambda t: t,
                  log=lambda ev, **kw: logs.append(ev), wait=3, sleep=lambda s: None, alive=alive)
    return r, keys, raws, logs


class DetectTests(unittest.TestCase):
    def test_detect(self):
        self.assertTrue(td.is_trust_dialog(DIALOG))
        self.assertTrue(td.is_trust_dialog("Do you trust the files in this folder?"))
        self.assertFalse(td.is_trust_dialog("❯ hello\n? for shortcuts"))

    def test_scrollback_mention_is_not_dialog(self):
        pane = "bu oturum 'trust this folder' diyalogunu konusuyor\n" + "x\n" * 40 + "❯ \n  ⏵⏵ auto mode on (shift+tab to cycle)"
        self.assertFalse(td.is_trust_dialog(pane))
        near = "trust this folder anlatisi\n❯ \n  ⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt"
        self.assertFalse(td.is_trust_dialog(near))

    def test_yes_option(self):
        self.assertEqual(td.yes_option(DIALOG), ("1", True))
        self.assertEqual(td.yes_option(DIALOG_NO_PTR), ("1", False))
        self.assertIsNone(td.yes_option("1. No\n"))


class HandleTests(unittest.TestCase):
    def test_registered_pointer_on_yes_presses_enter_only(self):
        self.assertEqual(run(DIALOG)[:3], ("accepted", ["Enter"], []))

    def test_registered_pointer_elsewhere_types_digit_then_enter(self):
        self.assertEqual(run(DIALOG_NO_PTR)[:3], ("accepted", ["Enter"], ["1"]))

    def test_unregistered_never_touches_the_pane(self):
        r, keys, raws, logs = run(DIALOG, registered=False)
        self.assertEqual((r, keys, raws), ("unregistered", [], []))
        self.assertIn("trust_dialog_unregistered", logs)

    def test_no_dialog_exits_calm(self):
        self.assertEqual(run("❯ \n? for shortcuts")[0], "none")

    def test_late_dialog_after_splash_is_not_missed(self):
        """Splash/başlık (istem işareti YOK) 4 yoklama sürer, diyalog 5.'de gelir: kaçmamalı (7 Kas canlı hata)."""
        keys, polls = [], []
        def cap(n):
            polls.append(1)
            return "Claude Code v2\nWelcome" if len(polls) < 5 else DIALOG
        r = td.handle("n", True, capture=cap, send_key=lambda n, k: keys.append(k) or True, send_raw=lambda n, d: True,
                      strip=lambda t: t, log=lambda ev, **kw: None, wait=20, sleep=lambda s: None)
        self.assertEqual((r, keys), ("accepted", ["Enter"]))

    def test_splash_without_prompt_marker_eventually_exits(self):
        self.assertEqual(run("Claude Code v2\nWelcome")[0], "none")

    def test_dead_session_stops_polling(self):
        self.assertEqual(run(DIALOG, alive=lambda: False)[0], "none")


class StartDiesEarlyTests(unittest.TestCase):
    """Kırmızı test: `opened:true` görünüp kısa sürede kaybolan oturum 'başlatma başarısız' sayılmalı."""

    def _start(self, died, trust="none"):
        info = {"state": "active", "cli": "claude", "model": "m", "cwd": "/tmp/x", "permission_mode": "auto", "effort": "low"}
        sess = SimpleNamespace(name="p")
        logs = []
        with mock.patch.object(web, "_fleet_status", return_value={"p": info}), \
             mock.patch.object(web, "find_sessions", return_value=[]), \
             mock.patch.object(web, "spawn_session", return_value="new"), \
             mock.patch.object(web, "guard_lock", mock.MagicMock()), \
             mock.patch.object(web, "_wait_stable", return_value=True), \
             mock.patch.object(web, "_died_within", return_value=died), \
             mock.patch.object(web.trust_dialog, "handle", return_value=trust), \
             mock.patch.object(web, "diag_log", lambda ev, **kw: logs.append(ev)), \
             mock.patch.object(web.inst_mod, "mark_started"):
            return web._start("p"), logs

    def test_session_that_dies_is_reported_failed(self):
        out, logs = self._start(died=True)
        self.assertFalse(out["ok"])
        self.assertIn("start_failed", logs)

    def test_healthy_session_ok(self):
        self.assertTrue(self._start(died=False)[0]["ok"])

    def test_unregistered_dialog_asks_owner(self):
        out, _ = self._start(died=False, trust="unregistered")
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()

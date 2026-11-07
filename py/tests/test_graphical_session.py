"""Panelden grafik oturumu öne alma: kullanıcıdan çözme, onay, kilit açmama, argv güvenliği. Gerçek loginctl'e DOKUNMAZ."""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claudeops import graphical_session as gs  # noqa: E402
from claudeops.commands import web, web_hosts  # noqa: E402


def cp(out="", rc=0, err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class FakeLogin:
    """İki oturum: 5 = me (fatihyuce), 1295 = ahmet. active: hangisi aktif."""
    def __init__(self, active="5", locked="no", activate_rc=0):
        self.active, self.locked, self.activate_rc, self.calls = active, locked, activate_rc, []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:3] == ["loginctl", "--no-legend", "list-sessions"]:
            return cp("1295 1001 ahmet seat0 tty3\n    5 1000 fatihyuce seat0 tty2\n")
        if argv[:2] == ["loginctl", "show-session"]:
            sid = argv[2]
            return cp(f"Active={'yes' if sid == self.active else 'no'}\nLockedHint={self.locked if sid == '5' else 'yes'}\nType=x11\nState=active\n")
        if argv[:2] == ["loginctl", "activate"]:
            if self.activate_rc == 0:
                self.active = argv[2]
            return cp("", self.activate_rc, "denied" if self.activate_rc else "")
        raise AssertionError(argv)


class Status(unittest.TestCase):
    def test_own_session_resolved_by_user_not_first_row(self):
        st = gs.status(FakeLogin(active="5"), user="fatihyuce")
        self.assertTrue(st["ok"])
        self.assertEqual(st["own"], {"id": "5", "active": True, "type": "x11", "locked": False})
        self.assertFalse(st["other_active"])

    def test_other_user_active(self):
        st = gs.status(FakeLogin(active="1295"), user="fatihyuce")
        self.assertTrue(st["other_active"])
        self.assertEqual(st["active_user"], "ahmet")
        self.assertFalse(st["own"]["active"])

    def test_no_own_session(self):
        st = gs.status(FakeLogin(), user="kimse")
        self.assertFalse(st["ok"])
        self.assertEqual(st["error"], "no_own_session")

    def test_never_raises(self):
        def boom(argv):
            raise OSError("x")
        self.assertFalse(gs.status(boom, user="fatihyuce")["ok"])


class Activate(unittest.TestCase):
    def test_already_active_no_activate_call(self):
        f = FakeLogin(active="5")
        self.assertEqual(gs.activate(run=f, user="fatihyuce")["already"], True)
        self.assertFalse([c for c in f.calls if c[1] == "activate"])

    def test_other_active_needs_confirm_and_names_user(self):
        f = FakeLogin(active="1295")
        r = gs.activate(run=f, user="fatihyuce")
        self.assertEqual((r["ok"], r["need_confirm"], r["active_user"]), (False, True, "ahmet"))
        self.assertFalse([c for c in f.calls if c[1] == "activate"])

    def test_confirm_activates_own_session_only(self):
        f = FakeLogin(active="1295")
        r = gs.activate(confirm=True, run=f, user="fatihyuce")
        self.assertTrue(r["ok"])
        self.assertEqual([c for c in f.calls if c[1] == "activate"], [["loginctl", "activate", "5"]])

    def test_no_unlock_ever(self):
        f = FakeLogin(active="1295", locked="yes")
        gs.activate(confirm=True, run=f, user="fatihyuce")
        self.assertFalse([c for c in f.calls if "unlock" in " ".join(c)])

    def test_failure_reported(self):
        r = gs.activate(confirm=True, run=FakeLogin(active="1295", activate_rc=1), user="fatihyuce")
        self.assertFalse(r["ok"])
        self.assertIn("denied", r["error"])

    def test_non_numeric_session_id_refused(self):
        def run(argv):
            if argv[:3] == ["loginctl", "--no-legend", "list-sessions"]:
                return cp("5; 1000 me seat0\n")      # rakam dışı kimlik satırı eleniyor
            raise AssertionError(argv)
        self.assertEqual(gs.activate(confirm=True, run=run, user="me")["error"], "no_own_session")


class Setting(unittest.TestCase):
    def test_default_off(self):
        with mock.patch.object(gs.settings, "load_settings", return_value={}):
            self.assertFalse(gs.auto_activate_enabled())
        from claudeops.settings import DEFAULT_SETTINGS
        self.assertEqual(DEFAULT_SETTINGS["session_auto_activate"], "off")

    def test_on_words_only(self):
        for v, want in (("on", True), ("true", True), ("off", False), ("", False), ("belki", False), (None, False)):
            with mock.patch.object(gs.settings, "load_settings", return_value={"session_auto_activate": v}):
                self.assertEqual(gs.auto_activate_enabled(), want, v)


class Routing(unittest.TestCase):
    def test_paths_registered(self):
        self.assertIn("/api/session/activate", web_hosts.HOST_ROUTED_PATHS)
        self.assertIn("/api/session/graphical", web_hosts.GET_HOST_ROUTED_PATHS)


if __name__ == "__main__":
    unittest.main()

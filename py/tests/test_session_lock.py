"""Uzak Masaüstü Kilitle / Kilidi aç: yalnız kendi oturumumuz, onay, ayarla kapatma, insan-dışı ret, olay günlüğü. Gerçek loginctl'e DOKUNMAZ."""
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claudeops import graphical_session as gs  # noqa: E402
from claudeops.commands import web  # noqa: E402


def cp(out="", rc=0, err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class Login:
    """5 = me (fatihyuce, grafik), 1295 = ahmet (başka kullanıcı), 3/4 = ssh/tty. lock/unlock `apply` kadar sonra uygulanır."""
    def __init__(self, locked="no", rc=0, effective=True):
        self.locked, self.rc, self.effective, self.calls = locked, rc, effective, []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:3] == ["loginctl", "--no-legend", "list-sessions"]:
            return cp("1295 1001 ahmet seat0 tty3\\n".replace("\\n", "\n") + "    3 1000 fatihyuce pts/0\n    4 1000 fatihyuce seat0 tty5\n    5 1000 fatihyuce seat0 tty2\n")
        if argv[:2] == ["loginctl", "show-session"]:
            sid = argv[2]
            if sid in ("3", "4"):
                return cp(f"Active=no\nLockedHint=no\nType={'ssh' if sid == '3' else 'tty'}\nState=online\n")
            return cp(f"Active={'yes' if sid == '5' else 'no'}\nLockedHint={self.locked if sid == '5' else 'yes'}\nType=x11\nState=active\n")
        if argv[:2] in (["loginctl", "lock-session"], ["loginctl", "unlock-session"]):
            if self.rc == 0 and self.effective:
                self.locked = "yes" if argv[1] == "lock-session" else "no"
            return cp("", self.rc, "denied" if self.rc else "")
        raise AssertionError(argv)

    def acted(self):
        return [c for c in self.calls if c[1] in ("lock-session", "unlock-session")]


def lock(action, login, **kw):
    kw.setdefault("wait", 0)
    return gs.set_lock(action, run=login, user="fatihyuce", sleep=lambda s: None, **kw)


class SetLock(unittest.TestCase):
    def test_lock_and_unlock_target_only_own_graphical_session(self):
        lg = Login("no")
        r = lock("lock", lg, confirm=True)
        self.assertEqual((r["ok"], r["locked"]), (True, True))
        self.assertEqual(lg.acted(), [["loginctl", "lock-session", "5"]])          # ahmet (1295), ssh (3), tty (4) ASLA
        lg2 = Login("yes")
        r = lock("unlock", lg2, confirm=True)
        self.assertEqual((r["ok"], r["locked"]), (True, False))
        self.assertEqual(lg2.acted(), [["loginctl", "unlock-session", "5"]])

    def test_confirm_required_and_nothing_runs_without_it(self):
        for action, st in (("lock", "no"), ("unlock", "yes")):
            lg = Login(st)
            r = lock(action, lg)
            self.assertEqual((r["ok"], r.get("need_confirm")), (False, True))
            self.assertEqual(lg.acted(), [])

    def test_already_in_state_is_noop(self):
        lg = Login("yes")
        r = lock("lock", lg, confirm=True)
        self.assertEqual((r["ok"], r["already"]), (True, True))
        self.assertEqual(lg.acted(), [])
        lg = Login("no")
        self.assertTrue(lock("unlock", lg, confirm=True)["already"])
        self.assertEqual(lg.acted(), [])

    def test_unlock_setting_off_disables_unlock_only(self):
        with mock.patch.object(gs.settings, "load_settings", return_value={"remote_desktop": {"unlock": "off"}}):
            self.assertFalse(gs.unlock_enabled())
            lg = Login("yes")
            r = lock("unlock", lg, confirm=True)
            self.assertEqual((r["ok"], r["error"]), (False, "unlock_disabled"))
            self.assertEqual(lg.acted(), [])
            self.assertEqual(lock("lock", Login("no"), confirm=True)["ok"], True)    # kilitleme kapatılmaz
            self.assertFalse(gs.status(Login("yes"), "fatihyuce")["unlock_enabled"])

    def test_unlock_setting_default_on_and_tolerant(self):
        for raw in ({}, None, "x", {"unlock": ""}, {"unlock": "on"}, {"unlock": "garbage"}):
            with mock.patch.object(gs.settings, "load_settings", return_value={"remote_desktop": raw}):
                self.assertTrue(gs.unlock_enabled(), raw)
        for v in ("off", "OFF", "0", "false", "no"):
            with mock.patch.object(gs.settings, "load_settings", return_value={"remote_desktop": {"unlock": v}}):
                self.assertFalse(gs.unlock_enabled(), v)

    def test_failures(self):
        self.assertEqual(lock("reboot", Login(), confirm=True)["error"], "bad_action")
        r = lock("unlock", Login("yes", rc=1), confirm=True)
        self.assertEqual((r["ok"], r["error"]), (False, "denied"))
        r = lock("unlock", Login("yes", effective=False), confirm=True)               # komut geçti ama kilit değişmedi
        self.assertEqual((r["ok"], r["locked"]), (False, True))
        r = gs.set_lock("lock", confirm=True, run=Login(), user="nobody", wait=0)
        self.assertEqual((r["ok"], r["error"]), (False, "no_own_session"))


class FakeH:
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.client_address = ("192.168.1.9", 5555)
        self.out = None
        self.status = None
        self.wfile = io.BytesIO()

    def _json(self, obj, status=200):
        self.out, self.status = obj, status


class Endpoint(unittest.TestCase):
    def call(self, action, data, headers=None, set_lock=None):
        h = FakeH(headers)
        with mock.patch.object(web.graphical_session, "set_lock", set_lock or mock.Mock(return_value={"ok": True, "locked": True})) as sl, \
                mock.patch.object(web, "diag_log") as dl:
            web._Handler._session_lock(h, action, data)
        return h, sl, dl

    def test_human_confirm_logged(self):
        h, sl, dl = self.call("lock", {"confirm": True})
        self.assertEqual((h.status, h.out["ok"]), (200, True))
        sl.assert_called_once_with("lock", confirm=True)
        kw = dl.call_args.kwargs
        self.assertEqual((dl.call_args.args[0], kw["action"], kw["ip"], kw["actor"], kw["ok"]), ("session_lock", "lock", "192.168.1.9", "human", True))

    def test_remote_host_refused(self):
        h, sl, _ = self.call("unlock", {"confirm": True, "host": "yuhem"})
        self.assertEqual((h.status, h.out["error"]), (400, "local_only"))
        sl.assert_not_called()

    def test_non_human_actor_and_agent_token_refused(self):
        for data in ({"confirm": True, "actor": "brain"}, {"confirm": True, "actor": "mcp"}):
            h, sl, dl = self.call("unlock", data)
            self.assertEqual((h.status, h.out["error"]), (403, "human_only"))
            sl.assert_not_called()
            self.assertEqual(dl.call_args.args[0], "session_lock_refused")
        with mock.patch.object(web.ucli_agents, "parent_for_token", return_value="somesession"):
            h, sl, _ = self.call("unlock", {"confirm": True}, headers={"Authorization": "Bearer agenttok"})
        self.assertEqual(h.status, 403)
        sl.assert_not_called()

    def test_unlock_disabled_is_403(self):
        h, _, _ = self.call("unlock", {"confirm": True}, set_lock=mock.Mock(return_value={"ok": False, "error": "unlock_disabled"}))
        self.assertEqual(h.status, 403)

    def test_routes_are_post_allowlisted_and_local_only(self):
        src = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn('"/api/session/lock", "/api/session/unlock"', src)
        from claudeops.commands import web_hosts
        for p in ("/api/session/lock", "/api/session/unlock"):
            self.assertNotIn(p, web_hosts.HOST_ROUTED_PATHS)


if __name__ == "__main__":
    unittest.main()

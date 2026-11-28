"""Sahipsiz kaynak denetimi: yardımcı tmux soketleri (ölü soket silinir, yaşlı+sahibi ölü rapor, yalnız cops-usage-* kapatılır)
ve tanınmayan yaşlı CLI süreçleri (öldürme YOK); periyodik iş yeni anomalide tek bildirim."""
import os
import shutil
import socket
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import orphan_watch as ow  # noqa: E402
from claudeops import periodic  # noqa: E402

NOW = 1_000_000.0
ME = types.SimpleNamespace(real=os.getuid())     # içerik yalnız kendi sürecimizde okunur (TBD#365)


class Sockets(unittest.TestCase):
    def setUp(self):
        # AF_UNIX yolu en çok 107 bayt: uzun TMPDIR'de (ör. iç içe geçici dizin) bind "path too long" verirdi
        base = "/tmp" if len(tempfile.gettempdir()) > 40 and os.path.isdir("/tmp") else None
        self.d = tempfile.mkdtemp(prefix="cops-ow-", dir=base)
        self.addCleanup(shutil.rmtree, self.d, True)
        self.socks = []
        self.alive = set()
        self.calls = []

    def mk(self, name, age=0.0):
        path = os.path.join(self.d, name)
        s = socket.socket(socket.AF_UNIX)
        s.bind(path)
        self.socks.append(s)
        self.addCleanup(s.close)
        os.utime(path, (NOW - age, NOW - age))
        return path

    def run_(self, argv, **k):
        self.calls.append(argv)
        name = argv[2]
        rc = 0 if (argv[3] == "list-sessions" and name in self.alive) else (0 if argv[3] == "kill-server" else 1)
        return types.SimpleNamespace(returncode=rc, stdout="")

    def scan(self, pid_alive=lambda p: False):
        return ow.scan_sockets(now=NOW, sock_dir=self.d, run=self.run_, pid_alive=pid_alive)

    def test_dead_server_socket_deleted(self):
        p = self.mk("cops_e2e_x")
        r = self.scan()
        self.assertEqual(r["deleted"], ["cops_e2e_x"])
        self.assertFalse(os.path.exists(p))

    def test_live_server_owner_dead_old_reported_not_killed(self):
        self.mk("cops_e2e_y123", age=7200)
        self.alive.add("cops_e2e_y123")
        r = self.scan()
        self.assertEqual([o["name"] for o in r["orphans"]], ["cops_e2e_y123"])
        self.assertFalse(any(c[3] == "kill-server" for c in self.calls))

    def test_young_or_owner_alive_not_reported(self):
        self.mk("cops_e2e_a1", age=60)
        self.mk("cops_e2e_b2", age=7200)
        self.alive.update({"cops_e2e_a1", "cops_e2e_b2"})
        self.assertEqual(self.scan(pid_alive=lambda p: p == 2)["orphans"], [])

    def test_usage_socket_killed_and_removed(self):
        p = self.mk("cops-usage-copilot-424242", age=7200)
        self.alive.add("cops-usage-copilot-424242")
        r = self.scan()
        self.assertEqual(r["killed"], ["cops-usage-copilot-424242"])
        self.assertFalse(os.path.exists(p))

    def test_main_and_foreign_sockets_ignored(self):
        self.mk("cops", age=99999)
        self.mk("default", age=99999)
        self.assertEqual(self.scan(), {"deleted": [], "killed": [], "orphans": []})


class P:
    """`process_iter` öğesi (`.info` YALNIZ bunlarda var); üst süreç hep `Parent`."""

    def __init__(self, pid, name, age, parent=None, cmdline=()):
        assert not hasattr(parent, "info"), "parent() sahtesi .info taşımamalı"
        self.pid = pid
        self.info = {"pid": pid, "name": name, "create_time": NOW - age, "cwd": "/tmp/x", "cmdline": list(cmdline), "uids": ME}
        self._parent = parent

    def parent(self):
        return self._parent


class Parent:
    """`psutil.Process.parent()` gerçekte `.info` taşımaz."""

    def __init__(self, pid, cmdline):
        self.pid = pid
        self._cmd = list(cmdline)

    def cmdline(self):
        return self._cmd

    def uids(self):
        return ME

    def parent(self):
        return None


class Procs(unittest.TestCase):
    def test_app_server_child_skipped_when_parent_has_no_info(self):
        child = P(10, "codex", 7200, parent=Parent(9, ["codex", "app-server"]))
        self.assertEqual(self.scan([child]), [])
        other = P(11, "codex", 7200, parent=Parent(9, ["bash"]))
        self.assertEqual([p["pid"] for p in self.scan([other])], [11])

    def scan(self, procs, known=(), panes=()):
        return ow.scan_procs(known, now=NOW, procs=procs, pane_pids=set(panes))

    def test_old_unknown_cli_flagged_young_and_known_not(self):
        got = self.scan([P(10, "claude", 7200), P(11, "claude", 60), P(12, "codex", 9000), P(13, "bash", 9000)], known=[12])
        self.assertEqual([x["pid"] for x in got], [10])

    def test_under_cops_pane_or_known_ancestor_not_flagged(self):
        top = Parent(100, ["bash"])
        self.assertEqual(self.scan([P(20, "copilot", 9000, parent=top)], panes=[100]), [])
        self.assertEqual(self.scan([P(21, "copilot", 9000, parent=top)], known=[100]), [])
        self.assertEqual([x["pid"] for x in self.scan([P(22, "copilot", 9000, parent=top)])], [22])

    def test_chrome_native_host_ignored(self):
        self.assertEqual(self.scan([P(30, "claude", 9000, cmdline=["claude", "--chrome-native-host"])]), [])


    def test_codex_app_server_and_its_children_ignored(self):
        srv = P(40, "codex", 9000, cmdline=["codex", "app-server"])
        self.assertEqual(self.scan([srv]), [])
        self.assertEqual(self.scan([P(41, "codex", 9000, parent=Parent(40, ["codex", "app-server"]))]), [])


class Job(unittest.TestCase):
    def run_job(self, keys, state):
        res = {"ok": True, "keys": keys, "sockets": {"deleted": [], "killed": [], "orphans": [{"name": "k"}] if keys else []},
               "procs": []}
        with mock.patch.object(ow, "check", return_value=res), \
                mock.patch("claudeops.commands.web_steward.notify_phone", return_value=True) as n:
            out = periodic.run_orphan_watch({"_name": "orphan_watch"}, True, state)
        return out, n

    def test_notifies_only_new_keys_and_forgets_resolved(self):
        st = {}
        out, n = self.run_job(["sock:a"], st)
        self.assertTrue(out["ok"])
        n.assert_called_once()
        out, n = self.run_job(["sock:a"], st)
        n.assert_not_called()                       # aynı anomali: tekrar bildirim yok
        out, n = self.run_job([], st)
        self.assertEqual(st["orphan_watch"]["notified"], [])
        out, n = self.run_job(["sock:a"], st)
        n.assert_called_once()                      # çözülüp yeniden çıktı: yeniden bildirilir

    def test_registered_as_light_job(self):
        self.assertIn("orphan_watch", periodic.JOBS)
        self.assertTrue(periodic._is_light("orphan_watch"))


if __name__ == "__main__":
    unittest.main()

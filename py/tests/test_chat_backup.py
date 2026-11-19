import os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeops import chat_backup as cb  # noqa: E402


class T(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        for k, v in (("UNIT_DIR", os.path.join(self.td, "u")), ("DEST", os.path.join(self.td, "d")),
                     ("SCRIPT", os.path.join(self.td, "m.sh")), ("SETTINGS", os.path.join(self.td, "s.json"))):
            p = mock.patch.object(cb, k, v); p.start(); self.addCleanup(p.stop)

    def test_status_not_installed_and_log(self):
        os.makedirs(cb.DEST)
        open(os.path.join(cb.DEST, "mirror.log"), "w").write("2026-11-19 03:17:01 ok x\n2026-11-19 03:17:09 done 16G\n")
        open(cb.SETTINGS, "w").write('{"cleanupPeriodDays": 36500}')
        s = cb.status()
        self.assertEqual((s["installed"], s["cleanup_period_days"]), (False, 36500))
        self.assertIn("done 16G", s["last_done"])

    def test_install_writes_units_and_enables(self):
        open(cb.SCRIPT, "w").write("#!/bin/bash\n")
        calls = []
        def fake(*a):
            calls.append(a); return mock.Mock(returncode=0, stdout="enabled\n", stderr="")
        with mock.patch.object(cb, "_sysctl", fake):
            r = cb.install()
        self.assertTrue(r["ok"], r)
        self.assertEqual(calls[:2], [("daemon-reload",), ("enable", "--now", cb.UNIT + ".timer")])
        self.assertIn("OnCalendar", open(os.path.join(cb.UNIT_DIR, cb.UNIT + ".timer")).read())

    def test_install_failure_gives_manual_command(self):
        open(cb.SCRIPT, "w").write("x")
        with mock.patch.object(cb, "_sysctl", lambda *a: mock.Mock(returncode=1, stdout="", stderr="denied")):
            r = cb.install()
        self.assertFalse(r["ok"]); self.assertIn("systemctl --user", r["manual_command"])

    def test_missing_script(self):
        self.assertFalse(cb.install()["ok"]); self.assertFalse(cb.run_now()["ok"])


if __name__ == "__main__":
    unittest.main()

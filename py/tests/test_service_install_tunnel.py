"""`service install` tunnel'i yalniz unit/betik degisince, tunnel calismiyorsa ya da --restart-tunnel ile restart eder
(quick-tunnel'da her restart URL'i degistirir). systemctl/loginctl sahte; gercek dosyalara dokunulmaz."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import check, service  # noqa: E402

WEB, TUNNEL = service.UNIT_NAMES


class InstallTunnelRestartTest(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp(prefix="cops-svc-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.src = d / "src.sh"
        self.src.write_text("#!/bin/bash\necho v1\n")
        self.calls = []
        self.tunnel_state = "active"
        self.check_errors = []
        patches = {
            "CLAUDEOPS_DIR": str(d / "state"), "SYSTEMD_USER_DIR": d / "units",
            "WEB_UNIT": d / "units" / WEB, "TUNNEL_UNIT": d / "units" / TUNNEL,
            "RUN_TUNNEL_SRC": self.src, "RUN_TUNNEL_DEST": d / "state" / "run-tunnel.sh",
            "TUNNEL_APPLIED_FILE": d / "state" / "tunnel_applied.sha256",
            "TUNNEL_LABEL_FILE": d / "state" / "tunnel_label.txt",
            "TUNNEL_LOG": d / "state" / "tunnel.log", "_sh": self._fake_sh,
        }
        for name, value in patches.items():
            p = mock.patch.object(service, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(check, "run_checks", lambda path: list(self.check_errors))
        p.start()
        self.addCleanup(p.stop)

    def _fake_sh(self, *args):
        self.calls.append(args)
        out = self.tunnel_state + "\n" if "is-active" in args else ""
        return subprocess.CompletedProcess(args, 0, out, "")

    def _install(self, **kw):
        self.calls = []
        args = Namespace(tunnel_name="claudeops", label="", cloudflared_protocol="", restart_tunnel=False)
        vars(args).update(kw)
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            return service.run_install(args)

    def _restarted(self):
        units = [a for c in self.calls if "restart" in c for a in c[c.index("restart") + 1:]]
        return units

    def test_fresh_install_restarts_both(self):
        self.assertEqual(self._install(), 0)
        self.assertEqual(self._restarted(), [WEB, TUNNEL])

    def test_unchanged_rerun_restarts_web_only(self):
        self._install()
        self.assertEqual(self._install(), 0)
        self.assertEqual(self._restarted(), [WEB])

    def test_existing_install_without_marker_keeps_url(self):
        self._install()
        service.TUNNEL_APPLIED_FILE.unlink()
        self._install()
        self.assertEqual(self._restarted(), [WEB])

    def test_changed_unit_restarts_tunnel(self):
        self._install()
        self._install(cloudflared_protocol="http2")
        self.assertEqual(self._restarted(), [WEB, TUNNEL])

    def test_changed_script_restarts_tunnel(self):
        self._install()
        self.src.write_text("#!/bin/bash\necho v2\n")
        self._install()
        self.assertEqual(self._restarted(), [WEB, TUNNEL])

    def test_inactive_tunnel_is_started(self):
        self._install()
        self.tunnel_state = "inactive"
        self._install()
        self.assertEqual(self._restarted(), [WEB, TUNNEL])

    def test_force_flag(self):
        self._install()
        self._install(restart_tunnel=True)
        self.assertEqual(self._restarted(), [WEB, TUNNEL])

    def test_change_survives_failed_check(self):
        self._install()
        service.TUNNEL_APPLIED_FILE.unlink()     # isaretsiz eski kurulum
        self.src.write_text("#!/bin/bash\necho v2\n")
        self.check_errors = ["bozuk"]
        self.assertEqual(self._install(), 1)
        self.assertEqual(self._restarted(), [])
        self.check_errors = []
        self._install()
        self.assertEqual(self._restarted(), [WEB, TUNNEL])


if __name__ == "__main__":
    unittest.main()

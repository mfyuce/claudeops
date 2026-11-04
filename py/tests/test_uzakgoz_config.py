"""`uzakgoz` ayarı (uzak masaüstü daemon'u, ayrı repo) + `remote_desktop` çözümü (stdlib unittest). Gerçek settings.json'a,
cargo'ya, ağa ya da sürece DOKUNMAZ: ayar okuma ve subprocess mock'lanır."""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import remote_desktop as rd  # noqa: E402
from claudeops import settings  # noqa: E402


def with_cfg(cfg):
    return mock.patch.object(settings, "load_settings", return_value={"uzakgoz": cfg})


class ConfigTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.d = t.name

    def test_defaults_when_empty_or_garbage(self):
        with mock.patch.object(settings, "UZAKGOZ_DEFAULT_DIR", os.path.join(self.d, "yok")):
            for raw in ({}, None, "x", {"port": "abc", "bin": "/yok"}):
                with with_cfg(raw):
                    self.assertEqual(settings.uzakgoz_config(), {"dir": "", "bin": "", "port": None})

    def test_dir_needs_cargo_toml(self):
        with with_cfg({"dir": self.d}):
            self.assertEqual(settings.uzakgoz_config()["dir"], "")
        Path(self.d, "Cargo.toml").write_text("[package]\n")
        with with_cfg({"dir": self.d}):
            self.assertEqual(settings.uzakgoz_config()["dir"], self.d)

    def test_bin_must_be_executable_file(self):
        f = Path(self.d, "b")
        f.write_text("x")
        with with_cfg({"bin": str(f)}):
            self.assertEqual(settings.uzakgoz_config()["bin"], "")
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
        with with_cfg({"bin": str(f)}):
            self.assertEqual(settings.uzakgoz_config()["bin"], str(f))

    def test_port_range(self):
        for raw, want in (("8877", 8877), ("80", None), ("70000", None), ("", None), ("9000", 9000)):
            with with_cfg({"port": raw}):
                self.assertEqual(settings.uzakgoz_config()["port"], want, raw)

    def test_save_merges_and_empty_removes(self):
        self.assertIn("uzakgoz", settings.DEFAULT_SETTINGS)


class ResolveTests(unittest.TestCase):
    def test_manifest_prefers_new_repo_else_legacy(self):
        with mock.patch.object(rd, "uzakgoz_config", return_value={"dir": "/x/uzakgoz", "bin": "", "port": None}):
            self.assertEqual(rd._manifest_path(), "/x/uzakgoz/Cargo.toml")
        with mock.patch.object(rd, "uzakgoz_config", return_value={"dir": "", "bin": "", "port": None}):
            self.assertEqual(rd._manifest_path(), rd.MANIFEST_PATH)

    def test_start_with_prebuilt_binary_skips_cargo_and_uses_port(self):
        cfg = {"dir": "", "bin": "/bin/true", "port": 9123}
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 4242
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(rd, "uzakgoz_config", return_value=cfg), \
                mock.patch.object(rd, "TOKEN_FILE", os.path.join(tmp.name, "t")), \
                mock.patch.object(rd, "_token", None), mock.patch.object(rd, "_port", None), \
                mock.patch.object(rd.subprocess, "run") as run, \
                mock.patch.object(rd.subprocess, "Popen", return_value=proc) as popen, \
                mock.patch.object(rd, "_port_open", return_value=True), \
                mock.patch.object(rd, "_write_pid_file"), \
                mock.patch.object(rd, "_adopt_if_orphaned"), \
                mock.patch.object(rd, "_proc", None), mock.patch.object(rd, "_adopted_pid", None):
            res = rd.start()
        self.assertEqual(res, {"ok": True, "port": 9123})
        run.assert_not_called()                                   # derleme yok
        self.assertEqual(popen.call_args[0][0], ["/bin/true", "9123", "--input"])


if __name__ == "__main__":
    unittest.main()

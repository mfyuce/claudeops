"""exec_toolchain=rust: kafeste GERÇEK cargo/rustc tam yolla, izinli ortam değişkenleriyle (2026-11-02 canlı bulgu: çıplak
cargo rustup vekili, kafeste $HOME boş; ucli yalnız izinli değişkenleri kabul eder, RUSTC yok)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import ucli_session_opts as so  # noqa: E402

_TC = {"root": "/h/.rustup/toolchains/1.98.0-x", "cargo": "/h/.rustup/toolchains/1.98.0-x/bin/cargo",
       "rustc": "/h/.rustup/toolchains/1.98.0-x/bin/rustc", "registry": "/nonexistent/registry",
       "git": "/nonexistent/git", "rustup_home": "/h/.rustup", "cargo_home": "/h/.cargo"}


class ExecToolchainTests(unittest.TestCase):
    def test_only_rust_is_accepted(self):
        out, err = so.validate_opts({"exec_cmds": ["git"], "exec_toolchain": "node"})
        self.assertEqual(out, {})
        self.assertIn("yalnız rust", err)

    def test_missing_toolchain_is_an_error_not_a_silent_skip(self):
        with mock.patch.object(so, "rust_toolchain", return_value=({}, "Rust araç zinciri bulunamadı")):
            out, err = so.validate_opts({"exec_toolchain": "rust"})
        self.assertEqual(out, {})
        self.assertIn("bulunamadı", err)

    def test_flags_use_real_binaries_and_only_allowed_env(self):
        with mock.patch.object(so, "rust_toolchain", return_value=(_TC, "")):
            out, err = so.validate_opts({"exec_cmds": ["git"], "exec_toolchain": "rust"})
            self.assertEqual(err, "")
            argv = so.exec_flags(out)
        cmd = argv[argv.index("--allow-exec-cmd") + 1].split(",")
        self.assertEqual(cmd, ["git", _TC["cargo"], _TC["rustc"]])
        env = [argv[i + 1] for i, a in enumerate(argv) if a == "--exec-env"]
        keys = {e.split("=", 1)[0] for e in env}
        self.assertEqual(keys, {"RUSTUP_HOME", "CARGO_HOME", "RUSTUP_TOOLCHAIN", "CARGO_NET_OFFLINE", "PATH"})
        self.assertNotIn("RUSTC", keys)       # ucli kafesi RUSTC'yi reddeder: başlatma ölürdü
        self.assertIn("RUSTUP_TOOLCHAIN=1.98.0-x", env)
        self.assertTrue(next(e for e in env if e.startswith("PATH=")).startswith("PATH=/h/.rustup/toolchains/1.98.0-x/bin:"))
        binds = [argv[i + 1] for i, a in enumerate(argv) if a == "--exec-bind-ro"]
        self.assertEqual(binds, [_TC["root"]])    # yalnız var olan registry/git dizinleri eklenir
        self.assertEqual(argv[argv.index("--exec-memory-mib") + 1], "32768")
        self.assertEqual(argv[argv.index("--exec-max-tasks") + 1], "4096")

    def test_no_toolchain_means_old_flags_unchanged(self):
        out, err = so.validate_opts({"exec_cmds": ["git"]})
        argv = so.exec_flags(out)
        self.assertEqual(err, "")
        self.assertNotIn("--exec-env", argv)
        self.assertNotIn("--exec-memory-mib", argv)

    def test_path_in_exec_cmds_is_still_rejected(self):
        out, err = so.validate_opts({"exec_cmds": ["/usr/bin/cargo"]})
        self.assertEqual(out, {})
        self.assertIn("yol", err)


if __name__ == "__main__":
    unittest.main()

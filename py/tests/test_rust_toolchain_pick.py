"""rust_toolchain: RUSTUP_TOOLCHAIN eşleşmezse başka bir araç zinciri SESSİZCE seçilmez."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_session_opts as opts  # noqa: E402


class RustToolchainPickTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        for n in ("stable-x86_64-unknown-linux-gnu",):
            b = os.path.join(self.home, ".rustup", "toolchains", n, "bin")
            os.makedirs(b)
            for t in ("cargo", "rustc"):
                open(os.path.join(b, t), "w").close()

    def call(self, env):
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.dict(os.environ, {"HOME": self.home}):
            os.environ.pop("RUSTUP_TOOLCHAIN", None)
            if "RUSTUP_TOOLCHAIN" in env:
                os.environ["RUSTUP_TOOLCHAIN"] = env["RUSTUP_TOOLCHAIN"]
            return opts.rust_toolchain()

    def test_single_toolchain_without_env(self):
        tc, err = self.call({})
        self.assertEqual(err, "")
        self.assertTrue(tc["root"].endswith("stable-x86_64-unknown-linux-gnu"))

    def test_prefix_match(self):
        tc, err = self.call({"RUSTUP_TOOLCHAIN": "stable"})
        self.assertEqual(err, "")
        self.assertTrue(tc)

    def test_mismatch_is_error_not_fallback(self):
        tc, err = self.call({"RUSTUP_TOOLCHAIN": "nightly"})
        self.assertEqual(tc, {})
        self.assertIn("nightly", err)


if __name__ == "__main__":
    unittest.main()

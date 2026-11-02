"""Geniş glob kabulü (`accept_risk`) + 16 KiB talimat uyarı ucu. Gerçek ayar/ağ/spawn YOK."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claudeops import ucli_session_opts as so  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


def _o(g, **kw):
    return {"exec_cmds": ["cargo"], "exec_own_glob": [g], **kw}


class BroadGlobTests(unittest.TestCase):
    def test_broad_rejected_without_accept(self):
        for g in ("*", "**", "**/*"):
            out, err = so.validate_opts(_o(g))
            self.assertEqual(out, {})
            self.assertIn("çok geniş glob", err)
            self.assertTrue(so.validate_opts(_o(g, accept_risk=False))[1])

    def test_broad_accepted_with_accept(self):
        for g in ("*", "**", "**/*"):
            out, err = so.validate_opts(_o(g, accept_risk=True))
            self.assertEqual(err, "")
            self.assertTrue(out["accept_risk"])
            self.assertEqual(out["exec_own_glob"], [g])

    def test_narrow_glob_has_no_accept_flag(self):
        out, err = so.validate_opts(_o("tests/**", accept_risk=True))
        self.assertEqual(err, "")
        self.assertNotIn("accept_risk", out)

    def test_always_rejected_even_when_accepted(self):
        for g in ("../x", "a/../b", "/etc/*", "-x", "a//b", "/"):
            self.assertTrue(so.validate_opts(_o(g, accept_risk=True))[1], g)

    def test_forbidden_cmds_never_open(self):
        for c in ("sh", "bash", "sudo", "env"):
            self.assertTrue(so.validate_opts({"exec_cmds": [c], "exec_own_glob": ["*"], "accept_risk": True})[1], c)

    def test_grant_logged_in_apply(self):
        opts, err = so.validate_opts(_o("**", accept_risk=True))
        self.assertEqual(err, "")
        with mock.patch.object(up, "binary_supports_flag", return_value=True), \
                mock.patch.object(up, "expand_exec_cmds", return_value=(["cargo"], "")), \
                mock.patch.object(up, "path_executables", return_value=["cargo"]), \
                mock.patch.object(up, "diag_log") as dl:
            argv, _ = up._apply_cli_opts(["ucli"], opts, "sess1", "/tmp", "")
        self.assertIn("--allow-exec-own-glob", argv)
        calls = [c for c in dl.call_args_list if c.args and c.args[0] == "ucli_grant"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs["name"], "sess1")
        self.assertEqual(calls[0].kwargs["globs"], ["**"])


class InstructionsCheckTests(unittest.TestCase):
    def test_sizes(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "AGENTS.md").write_bytes(b"x" * 30000)
            Path(d, "CLAUDE.md").write_bytes(b"x" * 100)
            r = up.instructions_check(d)
        self.assertEqual(r["limit"], 16384)
        self.assertEqual(r["files"], [{"name": "AGENTS.md", "bytes": 30000, "over": True},
                                      {"name": "CLAUDE.md", "bytes": 100, "over": False}])

    def test_exact_limit_not_over(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "CLAUDE.md").write_bytes(b"x" * 16384)
            self.assertFalse(up.instructions_check(d)["files"][0]["over"])

    def test_no_files_and_bad_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(up.instructions_check(d)["files"], [])
        for c in ("", "relative/dir", "/nonexistent/zzz", "/etc/hostname"):
            self.assertEqual(up.instructions_check(c)["files"], [], c)

    def test_symlink_escape_ignored(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as o:
            Path(o, "secret.md").write_bytes(b"x" * 20000)
            os.symlink(Path(o, "secret.md"), Path(d, "AGENTS.md"))
            self.assertEqual(up.instructions_check(d)["files"], [])

    def test_no_content_returned(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "CLAUDE.md").write_text("TOPSECRET")
            self.assertNotIn("TOPSECRET", str(up.instructions_check(d)))


if __name__ == "__main__":
    unittest.main()

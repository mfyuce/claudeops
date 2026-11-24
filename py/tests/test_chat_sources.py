"""chat_sources: kayıt yerleri listesi -> chat_mirror.sh üretimi (D1). Gerçek dosya sistemine yazmaz."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import chat_sources as cs  # noqa: E402


class MirrorScriptTests(unittest.TestCase):
    def test_default_covers_reviewer_copilot_ucli_usage(self):
        ids = {s.id for s in cs.default_sources()}
        for need in ("claude", "codex", "agy", "copilot", "reviewer-agy", "reviewer-reviews", "reviewer-claude-p", "ucli-usage"):
            self.assertIn(need, ids)

    def test_script_syntax_and_contents(self):
        body = cs.mirror_script()
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "m.sh")
            with open(f, "w") as fh:
                fh.write(body)
            self.assertEqual(subprocess.run(["bash", "-n", f]).returncode, 0)
        self.assertIn("agy_home*", body)
        self.assertIn("antigravity-cli/conversations", body)
        self.assertIn("session-store.db*", body)
        self.assertIn("ucli_usage", body)
        self.assertFalse([ln for ln in body.splitlines() if not ln.startswith("#") and "--delete" in ln])     # kaynakta silinen yedekte kalır

    def test_caches_and_credentials_never_included(self):
        body = cs.mirror_script()
        for bad in (".rustup", ".cargo"):
            self.assertNotIn("--include=" + bad, body)
        for s in cs.default_sources():
            if s.id == "reviewer-agy":
                self.assertEqual(s.excludes, ["*"])                              # yalnız açık include'lar (sohbet db'leri) girer
                self.assertFalse(any("oauth" in i or "google_accounts" in i for i in s.includes))
        for s in cs.default_sources():
            if s.id == "reviewer-reviews":
                for sec in ("auth.json", "google_accounts.json", "*oauth-token*", "settings.json"):
                    self.assertIn(sec, s.excludes)

    def test_credentials_excluded_from_every_source_but_oauth_named_chats_kept(self):
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "g")
            os.makedirs(os.path.join(root, "antigravity-cli"))
            names = ("antigravity-oauth-token", "installation_id", "settings.json", "oauth_creds.json", "feedback_oauth.md")
            for n in names:
                with open(os.path.join(root, "antigravity-cli", n), "w") as f:
                    f.write("x")
            src = cs.Source("t", "x", "main", root, "g", includes=["*oauth*", "antigravity-cli/"])    # include, kimlik dışlamasını yenemez
            f = os.path.join(d, "m.sh")
            with open(f, "w") as fh:
                fh.write(cs.mirror_script([src]).replace("$HOME/.claude/claudeops/backups/chat-mirror", os.path.join(d, "dst")))
            subprocess.run(["bash", f], check=True, env=dict(os.environ, HOME=d))
            self.assertEqual(os.listdir(os.path.join(d, "dst", "g", "antigravity-cli")), ["feedback_oauth.md"])

    def test_remote_archive_excludes_credentials(self):
        from claudeops import chat_remote as cr
        cmd = cr.pack_command("yuhem", "20261125", outdir="/tmp")
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".gemini", "antigravity-cli"))
            for n in ("antigravity-oauth-token", "auth.lock", "keep.db"):
                with open(os.path.join(d, ".gemini", "antigravity-cli", n), "w") as f:
                    f.write("x")
            ex = [f"--exclude={e}" for e in cr.EXCLUDES]
            out = subprocess.run(f"tar cf - {' '.join(map(__import__('shlex').quote, ex))} -C {d} .gemini | tar tf -",
                                 shell=True, capture_output=True, text=True, check=True).stdout
        self.assertIn("keep.db", out)
        self.assertNotIn("oauth-token", out)
        self.assertNotIn("auth.lock", out)
        self.assertIn("oauth-token", cmd)

    def test_disabled_source_omitted_and_write_is_idempotent(self):
        srcs = [cs.Source("a", "x", "main", "/tmp/nonexistent-a", "a"), cs.Source("b", "x", "main", "/tmp/nonexistent-b", "b", backup=False)]
        body = cs.mirror_script(srcs)
        self.assertIn("nonexistent-a", body)
        self.assertNotIn("nonexistent-b", body)
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "sub", "m.sh")
            self.assertTrue(cs.write_mirror_script(f, srcs))
            self.assertFalse(cs.write_mirror_script(f, srcs))
            self.assertTrue(os.access(f, os.X_OK))

    def test_glob_source_expands_per_match(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("agy_home", "agy_home_1"):
                os.makedirs(os.path.join(d, "root", n, ".gemini", "antigravity-cli", "conversations"))
                with open(os.path.join(d, "root", n, ".gemini", "antigravity-cli", "conversations", "a.db"), "w") as f:
                    f.write("x")
                os.makedirs(os.path.join(d, "root", n, ".rustup"))
                with open(os.path.join(d, "root", n, ".rustup", "junk"), "w") as f:
                    f.write("x")
            src = next(s for s in cs.default_sources() if s.id == "reviewer-agy")
            src.path = os.path.join(d, "root")
            script = cs.mirror_script([src]).replace("$HOME/.claude/claudeops/backups/chat-mirror", os.path.join(d, "dst"))
            f = os.path.join(d, "m.sh")
            with open(f, "w") as fh:
                fh.write(script)
            subprocess.run(["bash", f], check=True, env=dict(os.environ, HOME=d))
            out = os.path.join(d, "dst", "reviewer", "agy")
            for n in ("agy_home", "agy_home_1"):
                self.assertTrue(os.path.exists(os.path.join(out, n, ".gemini", "antigravity-cli", "conversations", "a.db")))
                self.assertFalse(os.path.exists(os.path.join(out, n, ".rustup")))


if __name__ == "__main__":
    unittest.main()

"""rs/prov G10: `ucli_chat_once` hata yolları (gerçek alt süreç, yalnız geçici dizindeki sahte betik; ağ/API yok)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_approval, ucli_client  # noqa: E402

KEY = "sk-g10-gizli-anahtar-0001"


class _Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(prefix="cops-g10-chat-")
        self.addCleanup(d.cleanup)
        self.d = d.name
        for p in (mock.patch.object(ucli_approval, "ROOT", os.path.join(self.d, "ucli_approval")),
                  mock.patch.object(ucli_client, "binary_supports_flag", lambda *a: True),
                  mock.patch("claudeops.diaglog.diag_log")):
            p.start()
            self.addCleanup(p.stop)

    def fake(self, body, name="ucli"):
        path = os.path.join(self.d, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return path

    def once(self, body, prompt="p", **kw):
        kw.setdefault("timeout", 10)
        return ucli_client.ucli_chat_once(self.d, prompt, binary=self.fake(body), **kw)

    def err(self, *a, **kw):
        with self.assertRaises(ucli_client.UcliError) as c:
            self.once(*a, **kw)
        return str(c.exception)


class ProcessErrors(_Base):
    def test_missing_binary_is_ucli_error(self):
        with self.assertRaises(ucli_client.UcliError):
            ucli_client.ucli_chat_once(self.d, "p", binary=os.path.join(self.d, "yok"))

    def test_non_utf8_output_is_ucli_error(self):
        self.assertIn("UTF-8", self.err("printf '\\377\\376'"))

    def test_nul_in_prompt_is_ucli_error(self):
        self.err("echo '{}'", prompt="a\0b")

    def test_non_object_output_is_ucli_error(self):
        for body in ("echo 5", "echo '\"error\"'", "echo '[1]'", "echo null"):
            self.assertIn("nesne", self.err(body), body)

    def test_deeply_nested_output_is_ucli_error(self):
        self.err("head -c 100000 /dev/zero | tr '\\0' '['")

    def test_child_does_not_inherit_stdin(self):
        r, w = os.pipe()
        saved = os.dup(0)
        try:
            os.write(w, b"cagiranin-girdisi\n")
            os.close(w)
            os.dup2(r, 0)
            got = self.once('read x; printf \'{"answer":"[%s]"}\' "$x"')
        finally:
            os.dup2(saved, 0)
            os.close(saved)
            os.close(r)
        self.assertEqual(got["answer"], "[]")

    def test_unopenable_approval_dir_is_ucli_error(self):
        with open(os.path.join(self.d, "ucli_approval"), "w") as f:
            f.write("dosya")
        self.err("echo '{}'", approval_run_key="r1")


class PromptFlagInjection(_Base):
    def test_hyphen_prompt_is_refused_before_spawn(self):
        mark = os.path.join(self.d, "calisti")
        for prompt in ("--allow-edit", "-x", "--allow-exec=sh", "- madde"):
            self.assertIn("'-'", self.err(f"touch {mark}; echo '{{}}'", prompt=prompt), prompt)
        self.assertFalse(os.path.exists(mark))

    def test_lone_hyphen_and_inner_hyphen_still_pass(self):
        for prompt in ("-", "a --allow-edit"):
            self.assertEqual(self.once("echo '{\"answer\":\"ok\"}'", prompt=prompt)["answer"], "ok")


class SecretRedaction(_Base):
    def test_explicit_key_never_reaches_error_text(self):
        for body in ('echo "bad key $UCLI_API_KEY" >&2; exit 2', 'echo "not json $UCLI_API_KEY"',
                     'printf \'{"error":"key %s"}\' "$UCLI_API_KEY"', 'echo "[\\"$UCLI_API_KEY\\"]"'):
            msg = self.err(body, api_key=KEY)
            self.assertNotIn(KEY, msg, body)
            self.assertIn("<redacted>", msg, body)

    def test_inherited_key_never_reaches_error_text(self):
        with mock.patch.dict(os.environ, {"UCLI_API_KEY": KEY}):
            self.assertNotIn(KEY, self.err('echo "bad key $UCLI_API_KEY" >&2; exit 2'))

    def test_env_name_with_trailing_newline_is_refused(self):
        with self.assertRaises(ucli_client.UcliError):
            ucli_client._subprocess_env("X_API_KEY\n", "v")

    def test_resume_error_is_redacted_in_record(self):
        ucli_approval.register("r1", self.d, "", [self.fake('echo "k=$UCLI_API_KEY" >&2; exit 2'), "chat"])
        ucli_approval.set_state("r1", "suspended")
        self.assertFalse(ucli_client.ucli_resume_approval("r1", "a1", api_key=KEY)["ok"])
        self.assertNotIn(KEY, ucli_approval.get("r1")["result"]["error"])


if __name__ == "__main__":
    unittest.main()

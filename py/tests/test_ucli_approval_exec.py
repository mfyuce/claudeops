"""S2: ucli_chat_once approval_run_key: 75 + suspended satırı hata değil, kayda `suspended` yazılır; opsiyon doğrulaması."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import ucli_approval as ap  # noqa: E402
from claudeops import ucli_client as uc  # noqa: E402
from claudeops import ucli_session_opts as so  # noqa: E402

ID = "a" * 32


class ApprovalExecTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = mock.patch.object(ap, "ROOT", self.d)
        p.start()
        self.addCleanup(p.stop)
        for n, v in (("resolve_binary", "/bin/ucli"), ("binary_supports_flag", True)):
            q = mock.patch.object(uc, n, return_value=v) if n == "resolve_binary" else mock.patch.object(uc, n, lambda *a, **k: v)
            q.start()
            self.addCleanup(q.stop)

    def run_once(self, rc, out, **kw):
        res = NS(returncode=rc, stdout=out, stderr="")
        with mock.patch.object(uc.subprocess, "run", return_value=res) as r:
            ret = uc.ucli_chat_once("/w", "do", approval_run_key="r1", extra_args=["--allow-edit", "--ask-edit"], **kw)
        return ret, r.call_args[0][0]

    def test_suspended_registered(self):
        ret, argv = self.run_once(75, '{"suspended":{"id":"%s","state":"x","resume":"y"}}\n' % ID, session="s1")
        self.assertEqual(ret["status"], "suspended")
        self.assertEqual(ret["approval_id"], ID)
        self.assertIn("--approval-dir", argv)
        self.assertEqual(argv[-1], "do")
        rec = ap.get("r1")
        self.assertEqual(rec["state"], "suspended")
        self.assertNotIn("do", rec["argv_resume"])
        self.assertIn("--allow-edit", rec["argv_resume"])

    def test_75_without_suspended_line_is_error(self):
        with self.assertRaises(uc.UcliError):
            self.run_once(75, "nothing")

    def test_bad_run_key(self):
        with self.assertRaises(uc.UcliError):
            uc.ucli_chat_once("/w", "x", approval_run_key="BAD KEY")

    def test_opts_validation(self):
        base = {"exec_cmds": ["ls"], "exec_write": True, "ask_edit": True}
        out, err = so.validate_opts({**base, "approval_dir": True})
        self.assertFalse(err)
        self.assertTrue(out.get("approval_dir"))
        _, err = so.validate_opts({"exec_cmds": ["ls"], "exec_write": True, "approval_dir": True})
        self.assertTrue(err)
        _, err = so.validate_opts({**base, "approval_dir": True, "ask_dir": True})
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()

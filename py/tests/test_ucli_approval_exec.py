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


class ResumeTest(ApprovalExecTest):
    def suspend(self, owner="ali"):
        res = NS(returncode=75, stdout='{"suspended":{"id":"%s"}}' % ID, stderr="")
        with mock.patch.object(uc.subprocess, "run", return_value=res):
            uc.ucli_chat_once("/w", "do", session="s1", approval_run_key="r1", approval_owner=owner,
                              extra_args=["--allow-edit", "--ask-edit"])

    def test_resume_done_and_argv_from_record(self):
        self.suspend()
        res = NS(returncode=0, stdout='{"answer":"ok"}', stderr="")
        with mock.patch.object(uc.subprocess, "run", return_value=res) as r:
            out = uc.ucli_resume_approval("r1", ID)
        argv = r.call_args[0][0]
        self.assertEqual(argv[-2:], ["--resume-approval", ID])
        self.assertNotIn("do", argv)
        self.assertEqual(out["status"], "done")
        self.assertEqual(ap.get("r1")["state"], "done")
        self.assertEqual(ap.get("r1")["result"]["answer"], "ok")

    def test_resume_chain_and_double_resume(self):
        self.suspend()
        res = NS(returncode=75, stdout='{"suspended":{"id":"%s"}}' % ("b" * 32), stderr="")
        with mock.patch.object(uc.subprocess, "run", return_value=res):
            out = uc.ucli_resume_approval("r1", ID)
        self.assertEqual(out["approval_id"], "b" * 32)
        self.assertEqual(ap.get("r1")["state"], "suspended")
        self.assertIsNotNone(ap.begin_resume("r1"))
        self.assertFalse(uc.ucli_resume_approval("r1", ID)["ok"])      # zaten resuming

    def test_resume_error_recorded(self):
        self.suspend()
        res = NS(returncode=2, stdout="", stderr="boom")
        with mock.patch.object(uc.subprocess, "run", return_value=res):
            self.assertFalse(uc.ucli_resume_approval("r1", ID)["ok"])
        self.assertEqual(ap.get("r1")["result"]["error"], "boom")

    def test_list_runs_owner_filter_hides_argv(self):
        self.suspend("ali")
        self.assertEqual([r["run_key"] for r in ap.list_runs("ali", all_users=False)], ["r1"])
        self.assertEqual(ap.list_runs("vera", all_users=False), [])
        self.assertNotIn("argv_resume", ap.list_runs()[0])

    def test_recover_resuming(self):
        self.suspend()
        ap.begin_resume("r1")
        self.assertEqual(ap.recover_resuming(), 1)
        self.assertEqual(ap.get("r1")["state"], "suspended")
        self.assertEqual(ap.recover_resuming(now=9e12), 1)
        self.assertEqual(ap.get("r1")["state"], "expired")

    def test_authz_resource_and_action(self):
        from claudeops import authz
        self.suspend()
        self.assertEqual(authz.action_for("GET", "/api/ucli/approvals"), "status.read")
        self.assertEqual(authz.action_for("POST", "/api/ucli/approvals"), "session.chat")
        r = authz.resources_from("/api/ucli/approvals", {}, {"run_key": "r1"})
        self.assertEqual((r[0].kind, r[0].name), ("session", "s1"))
        self.assertEqual(authz.resources_from("/api/ucli/approvals", {}, {"run_key": "zz"})[0].kind, "global")


if __name__ == "__main__":
    unittest.main()

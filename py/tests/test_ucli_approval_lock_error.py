"""TBD#383 (2): onay kaydı kilitlenemezse askıdaki koşu sessizce/istisnayla düşmesin, hata olarak bildirilsin."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_approval, ucli_client  # noqa: E402
from claudeops.atomic_json import LockError  # noqa: E402

BUSY = LockError("dizin.lock alınamadı")


class _Base(unittest.TestCase):
    def patch(self, obj, name, **kw):
        p = mock.patch.object(obj, name, **kw)
        m = p.start()
        self.addCleanup(p.stop)
        return m

    def setUp(self):
        self.patch(ucli_client, "_subprocess_env", return_value={})
        p = mock.patch("claudeops.diaglog.diag_log")
        p.start()
        self.addCleanup(p.stop)


class Register(_Base):
    def test_suspended_run_reports_error_with_approval_id(self):
        self.patch(ucli_client, "resolve_binary", return_value="/bin/ucli")
        self.patch(ucli_client, "binary_supports_flag", return_value=True)
        self.patch(ucli_client, "build_chat_argv", return_value=["/bin/ucli"])
        self.patch(ucli_approval, "dir_for", return_value="/yok")
        self.patch(ucli_approval, "parse_suspended", return_value={"id": "onay-7"})
        self.patch(ucli_approval, "register", side_effect=BUSY)
        self.patch(ucli_client.subprocess, "run", return_value=subprocess.CompletedProcess([], 75, "{}", ""))
        with self.assertRaises(ucli_client.UcliError) as c:
            ucli_client.ucli_chat_once("/c", "p", approval_run_key="k1")
        self.assertIn("onay-7", str(c.exception))


class Resume(_Base):
    def test_begin_resume_lock_error_is_returned(self):
        self.patch(ucli_approval, "begin_resume", side_effect=BUSY)
        r = ucli_client.ucli_resume_approval("k1", "onay-7")
        self.assertFalse(r["ok"])
        self.assertIn("alınamadı", r["error"])

    def test_set_result_lock_error_is_returned(self):
        self.patch(ucli_approval, "begin_resume", return_value=["/bin/ucli"])
        self.patch(ucli_approval, "set_result", side_effect=BUSY)
        for code, out in ((0, json.dumps({"answer": "a"})), (1, ""), (0, "bozuk")):
            with mock.patch.object(ucli_client.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], code, out, "")):
                r = ucli_client.ucli_resume_approval("k1", "onay-7")
            self.assertFalse(r["ok"], (code, out))
            self.assertIn("alınamadı", r["error"])


if __name__ == "__main__":
    unittest.main()

"""Sürdürülen koşunun sonucu kayda yazılamadıysa aynı onay yeniden başlatmadan sonra ikinci kez sürdürülemez."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_approval, ucli_client  # noqa: E402
from claudeops.atomic_json import LockError  # noqa: E402


class ConsumedApproval(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for p in (mock.patch.object(ucli_approval, "ROOT", os.path.join(d.name, "ucli_approval")),
                  mock.patch.object(ucli_client, "_subprocess_env", return_value={}),
                  mock.patch("claudeops.diaglog.diag_log")):
            p.start()
            self.addCleanup(p.stop)
        ucli_approval.register("k1", "/c", "", ["/bin/ucli"])
        ucli_approval.set_state("k1", "suspended")

    def resume(self, code, out):
        with mock.patch.object(ucli_client, "_run_grouped",
                               return_value=subprocess.CompletedProcess([], code, out, "")) as run, \
             mock.patch.object(ucli_approval, "set_result", side_effect=LockError("x.lock alınamadı")):
            r = ucli_client.ucli_resume_approval("k1", "onay-7")
        self.assertEqual(run.call_count, 1)
        return r

    def check_not_resumable(self):
        ucli_approval.recover_resuming()                        # panel yeniden başladı
        rec = ucli_approval.get("k1")
        self.assertEqual(rec["state"], "done")
        self.assertIn("error", rec["result"])
        self.assertIsNone(ucli_approval.begin_resume("k1"))

    def test_success_then_record_failure_is_not_resumed_again(self):
        self.assertFalse(self.resume(0, '{"answer": "a"}')["ok"])
        self.check_not_resumable()

    def test_consumed_run_refused_even_if_state_says_suspended(self):
        self.resume(0, '{"answer": "a"}')
        ucli_approval.set_state("k1", "suspended")
        self.assertIsNone(ucli_approval.begin_resume("k1"))

    def test_interrupted_resume_without_marker_still_recovers(self):
        self.assertIsNotNone(ucli_approval.begin_resume("k1"))      # süreç sürerken panel öldü
        ucli_approval.recover_resuming()
        self.assertEqual(ucli_approval.get("k1")["state"], "suspended")


if __name__ == "__main__":
    unittest.main()

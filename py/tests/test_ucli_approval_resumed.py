"""ucli sürdürmeye başlayınca `pending/<id>.json` durumunu `resumed` yapar: o kayıt artık bekleyen onay değildir.
Sonuç yazılmadan panel ölürse koşu "sürdürme çalıştı, sonuç yazılamadı" ile kapanır."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import ucli_approval  # noqa: E402


class ResumedApproval(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = mock.patch.object(ucli_approval, "ROOT", os.path.join(d.name, "ucli_approval"))
        p.start()
        self.addCleanup(p.stop)
        ucli_approval.register("k1", "/c", "", ["/bin/ucli"])

    def put(self, aid, status):
        path = os.path.join(ucli_approval.dir_for("k1"), "pending", aid + ".json")
        with open(path, "w") as f:
            json.dump({"id": aid, "kind": "edit", "tool": "write_file", "summary": "s",
                       "expires_at": 9e12, "status": status}, f)

    def interrupted(self, *statuses):
        """Sürdürme başlamışken panel yeniden başlar."""
        ucli_approval.set_state("k1", "suspended")
        self.assertIsNotNone(ucli_approval.begin_resume("k1"))
        for aid, status in statuses:
            self.put(aid, status)
        ucli_approval.recover_resuming()
        return ucli_approval.get("k1")

    def test_resumed_card_is_not_pending_or_answerable(self):
        self.put("a1", "resumed")
        self.assertEqual(ucli_approval.pending("k1"), [])
        self.assertEqual(ucli_approval.answer("k1", "a1", "approve"), (False, "no such pending approval"))

    def test_run_with_only_resumed_card_is_closed(self):
        rec = self.interrupted(("a1", "resumed"))
        self.assertEqual(rec["state"], "done")
        self.assertEqual(rec["result"], {"error": "resume ran but its result was not recorded"})
        self.assertIsNone(ucli_approval.begin_resume("k1"))

    def test_already_suspended_record_with_only_resumed_card_is_closed(self):
        ucli_approval.set_state("k1", "suspended")
        self.put("a1", "resumed")
        self.assertEqual(ucli_approval.recover_resuming(), 1)
        self.assertEqual(ucli_approval.get("k1")["state"], "done")

    def test_chained_suspension_keeps_only_the_new_card(self):
        rec = self.interrupted(("a1", "resumed"), ("a2", "pending"))
        self.assertEqual(rec["state"], "suspended")
        self.assertEqual([p["id"] for p in ucli_approval.list_runs()[0]["pending"]], ["a2"])

    def test_untouched_card_stays_resumable(self):
        rec = self.interrupted(("a1", "pending"))
        self.assertEqual(rec["state"], "suspended")
        self.assertIsNotNone(ucli_approval.begin_resume("k1"))


if __name__ == "__main__":
    unittest.main()

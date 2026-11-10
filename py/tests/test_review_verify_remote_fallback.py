"""10 Kas 2026: `review_verify_mode=self` iken yerel klasörü olmayan (uzak host'lu) projenin bulguları projenin oturumuna düşer."""
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class RemoteFallbackTest(unittest.TestCase):
    def _call(self, self_res, views):
        cfg = NS(review_verify_mode="self", sid="reviewer")
        with mock.patch.object(ws, "_human_only", return_value=None), \
                mock.patch.object(ws, "_reviewer_cfg", return_value=(cfg, None)), \
                mock.patch.object(ws.web_review, "verify_candidates", return_value=[{"id": "f1"}]), \
                mock.patch.object(ws.web_review, "self_verify", return_value=self_res) as sv, \
                mock.patch.object(ws, "_owner_project_views", return_value=("iso", views, None)) as ov:
            return ws.http_review_verify({"project": "oiso"}, sid="reviewer"), sv, ov

    def test_local_project_uses_self_verifier_only(self):
        res, sv, ov = self._call({"ok": True, "session": "self"}, [])
        self.assertEqual(res["session"], "self")
        ov.assert_not_called()

    def test_no_local_folder_falls_back_to_project_session(self):
        res, sv, ov = self._call({"ok": False, "code": "no_cwd"}, [])
        ov.assert_called_once()
        self.assertEqual(res["code"], "not_running")     # oturum yok: açılmaz, açık hata


if __name__ == "__main__":
    unittest.main()

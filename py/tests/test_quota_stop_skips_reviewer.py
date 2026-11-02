import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


class QuotaStopSkipsReviewer(unittest.TestCase):
    def test_reviewer_not_disabled_and_others_shut_down(self):
        cfgs = {"reviewer": mock.Mock(enabled=True, role="reviewer"), "default": mock.Mock(enabled=True, role="steward")}
        saved, shut = [], []
        with mock.patch.object(ws, "steward_ids", lambda: ["reviewer", "default"]), \
                mock.patch.object(ws, "steward_config", lambda sid="default": cfgs[sid]), \
                mock.patch.object(ws, "shutdown_start", lambda sid, **k: shut.append(sid)), \
                mock.patch("claudeops.settings.save_settings", lambda d: saved.append(d)), \
                mock.patch.object(ws.sw, "log_event", lambda *a, **k: None), \
                mock.patch.object(ws, "notify_phone", lambda *a, **k: None):
            ws._quota_stop("test", hard=False)
        self.assertEqual(shut, ["default"])
        self.assertEqual(saved, [])          # reviewer kapatılmadı


if __name__ == "__main__":
    unittest.main()

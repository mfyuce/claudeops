import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops import authz  # noqa: E402
from claudeops.commands import web  # noqa: E402


class HoStopEventTest(unittest.TestCase):
    def _run(self, ok):
        key = web._ho_stop_key("local", "n1")
        web._HO_STOP_JOBS[key] = {"state": "pending", "started": 0.0}
        self.addCleanup(web._HO_STOP_JOBS.pop, key, None)
        with mock.patch.object(web.web_steward, "human_stop_with_ho", return_value={"ok": ok}), \
                mock.patch.object(web.web_ws, "notify_status_changed"), \
                mock.patch.object(authz, "emit_event") as em:
            web._ho_stop_run(key, "local", "n1", "tr", principal="P")
        return em

    def test_emits_closed_event_on_success(self):
        self._run(True).assert_called_once_with("/api/stop", "local", "n1", "P")

    def test_no_event_on_failure(self):
        self._run(False).assert_not_called()


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


class DiagAskValueError(unittest.TestCase):
    def test_spawn_valueerror_forgets_instance_and_returns_clean_error(self):
        provider = mock.Mock()
        provider.permission_modes.return_value = ["default"]
        inst = mock.Mock()
        with mock.patch.object(web, "get_provider", lambda c: provider), \
                mock.patch.object(web, "default_model_for", lambda p: "m"), \
                mock.patch.object(web, "default_effort_for", lambda p: "high"), \
                mock.patch.object(web, "_generate_new_chat_name", lambda p: "diag1"), \
                mock.patch.object(web, "_diag_status", lambda: {"web_pid": 1, "web_uptime_seconds": 1, "gt": None}), \
                mock.patch.object(web, "diag_log_tail", lambda n: []), \
                mock.patch.object(web, "inst_mod", inst), \
                mock.patch.object(web, "guard_lock", mock.MagicMock()), \
                mock.patch.object(web, "detect_display", lambda: ":0"), \
                mock.patch.object(web, "spawn_session", mock.Mock(side_effect=ValueError("anahtar yok"))):
            res = web._diag_ask("claude")
        self.assertFalse(res["ok"])
        self.assertIn("anahtar yok", res["error"])
        inst.record_instance.assert_called_once()
        inst.forget_instance.assert_called_once_with("diag1")


if __name__ == "__main__":
    unittest.main()

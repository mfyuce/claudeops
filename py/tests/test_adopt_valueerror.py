import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web  # noqa: E402


class AdoptValueError(unittest.TestCase):
    def test_spawn_valueerror_returns_clean_error(self):
        proc = SimpleNamespace(pid=1, name="foo", cwd="/tmp", cli="claude", model="m")
        provider = mock.Mock()
        provider.permission_modes.return_value = ["default"]
        with mock.patch.object(web, "_find_running_for_action", lambda n: ("one", [proc])), \
                mock.patch.object(web, "_all_known_names", lambda: set()), \
                mock.patch.object(web, "get_provider", lambda c: provider), \
                mock.patch.object(web, "resolved_model_for", lambda p, m: "m"), \
                mock.patch.object(web, "default_effort_for", lambda p: "high"), \
                mock.patch.object(web, "guard_lock", mock.MagicMock()), \
                mock.patch.object(web, "kill_session_and_parent", lambda *a, **k: "clean"), \
                mock.patch.object(web, "HANDOVER_KILL_SETTLE_SECONDS", 0), \
                mock.patch.object(web, "detect_display", lambda: ":0"), \
                mock.patch.object(web, "diag_log", lambda *a, **k: None), \
                mock.patch.object(web, "spawn_session", mock.Mock(side_effect=ValueError("anahtar yok"))):
            res = web._adopt("foo")
        self.assertFalse(res["ok"])
        self.assertIn("anahtar yok", res["error"])

    def test_preflight_refusal_keeps_old_session_alive(self):
        # P4 #32: build_inner_command ValueError (anahtar yok / tavan) eski oturum ÖLDÜRÜLMEDEN döner.
        proc = SimpleNamespace(pid=1, name="foo", cwd="/tmp", cli="ucli", model="m")
        provider = mock.Mock()
        provider.accepts_cli_opts = True
        provider.permission_modes.return_value = ["default"]
        provider.build_inner_command.side_effect = ValueError("anahtar yok")
        kill = mock.Mock(return_value="clean")
        spawn = mock.Mock()
        with mock.patch.object(web, "_find_running_for_action", lambda n: ("one", [proc])), \
                mock.patch.object(web, "_all_known_names", lambda: set()), \
                mock.patch.object(web, "get_provider", lambda c: provider), \
                mock.patch.object(web, "resolved_model_for", lambda p, m: "m"), \
                mock.patch.object(web, "default_effort_for", lambda p: "high"), \
                mock.patch.object(web, "guard_lock", mock.MagicMock()), \
                mock.patch.object(web, "kill_session_and_parent", kill), \
                mock.patch.object(web, "diag_log", lambda *a, **k: None), \
                mock.patch.object(web, "spawn_session", spawn):
            res = web._adopt("foo")
        self.assertFalse(res["ok"])
        self.assertIn("anahtar yok", res["error"])
        kill.assert_not_called()
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()

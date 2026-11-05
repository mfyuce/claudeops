"""PROC-02: recover_stuck yalnız pid değil kill_session_and_parent ile öldürür (hepsi sahte; süreç YOK)."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops import stuck  # noqa: E402


class RecoverStuckTest(unittest.TestCase):
    def test_uses_parent_aware_kill(self):
        s = SimpleNamespace(name="vc1", pid=4242, cwd="/tmp", model="m", permission_mode="auto",
                            effort="high", cli="claude")
        info = SimpleNamespace(session=s)
        with mock.patch.object(stuck, "kill_session_and_parent", return_value="killed") as kp, \
                mock.patch.object(stuck, "kill_session") as ks, \
                mock.patch.object(stuck, "spawn_session", return_value="tmux"), \
                mock.patch.object(stuck, "get_provider", return_value=object()):
            out = stuck.recover_stuck(info, display=":0")
        kp.assert_called_once()
        self.assertEqual(kp.call_args.args[0], 4242)
        self.assertEqual(kp.call_args.kwargs.get("name"), "vc1")
        ks.assert_not_called()
        self.assertTrue(out.startswith("recovered"))

    def test_unknown_permission_uses_provider_default(self):
        # PROC-04 artığı: kip okunamadıysa sabit "auto" DEĞİL, sağlayıcının ilk kipi (ucli: salt okunur)
        from claudeops.providers import get_provider
        for cli in ("claude", "ucli", "agy"):
            s = SimpleNamespace(name="vc1", pid=4242, cwd="/tmp", model="m", permission_mode=None,
                                effort="high", cli=cli)
            with mock.patch.object(stuck, "kill_session_and_parent", return_value="killed"), \
                    mock.patch.object(stuck, "spawn_session", return_value="tmux") as sp:
                stuck.recover_stuck(SimpleNamespace(session=s), display=":0")
            self.assertEqual(sp.call_args.kwargs["permission_mode"], get_provider(cli).permission_modes()[0], cli)
        self.assertNotEqual(get_provider("ucli").permission_modes()[0], "auto")

    def test_dry_run_kills_nothing(self):
        s = SimpleNamespace(name="vc1", pid=1)
        with mock.patch.object(stuck, "kill_session_and_parent") as kp:
            self.assertEqual(stuck.recover_stuck(SimpleNamespace(session=s), display=":0", dry_run=True), "dry-run")
        kp.assert_not_called()


if __name__ == "__main__":
    unittest.main()

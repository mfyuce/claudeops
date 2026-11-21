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


    def _adopt_with_lock_recheck(self, second):
        """`second`: kilit İÇİNDEKİ yeniden çözüm (TODO 1005 deseni). Öldürme ve spawn çağrıları döner."""
        proc = SimpleNamespace(pid=1, name="foo", cwd="/tmp", cli="claude", model="m")
        provider = mock.Mock()
        provider.accepts_cli_opts = False
        provider.permission_modes.return_value = ["default"]
        seq = [("one", [proc]), second]
        kill, spawn = mock.Mock(return_value="clean"), mock.Mock(return_value="new")
        with mock.patch.object(web, "_find_running_for_action", lambda *a, **k: seq.pop(0) if len(seq) > 1 else seq[0]), \
                mock.patch.object(web, "_all_known_names", lambda: set()), \
                mock.patch.object(web, "get_provider", lambda c: provider), \
                mock.patch.object(web, "resolved_model_for", lambda p, m: "m"), \
                mock.patch.object(web, "default_effort_for", lambda p: "high"), \
                mock.patch.object(web, "guard_lock", mock.MagicMock()), \
                mock.patch.object(web, "kill_session_and_parent", kill), \
                mock.patch.object(web, "HANDOVER_KILL_SETTLE_SECONDS", 0), \
                mock.patch.object(web, "detect_display", lambda: ":0"), \
                mock.patch.object(web, "diag_log", lambda *a, **k: None), \
                mock.patch.object(web, "spawn_session", spawn):
            res = web._adopt("foo")
        return res, kill, spawn

    def test_target_gone_or_ambiguous_inside_the_lock_kills_and_spawns_nothing(self):
        # kuru çalıştırma ön kontrolü spawn'ı bir kez çağırır (dry_run=True): gerçek spawn = dry_run olmayan çağrı
        for second in (("none", []), ("ambiguous", [SimpleNamespace(pid=2, name="foo2"), SimpleNamespace(pid=3, name="foo3")])):
            res, kill, spawn = self._adopt_with_lock_recheck(second)
            self.assertFalse(res["ok"], second[0])
            kill.assert_not_called()
            self.assertTrue(all(c.kwargs.get("dry_run") for c in spawn.call_args_list), second[0])

    def test_generic_dry_run_preflight_keeps_old_session_alive(self):
        # review P2: herhangi bir provider'da spawn kuru çalıştırması ValueError verirse eski oturum ÖLDÜRÜLMEZ.
        proc = SimpleNamespace(pid=1, name="foo", cwd="/tmp", cli="claude", model="m")
        provider = mock.Mock()
        provider.accepts_cli_opts = False
        provider.permission_modes.return_value = ["default"]
        kill = mock.Mock(return_value="clean")
        spawn = mock.Mock(side_effect=ValueError("hizmet anahtarı yok"))
        with mock.patch.object(web, "_find_running_for_action", lambda n: ("one", [proc])), \
                mock.patch.object(web, "_all_known_names", lambda: set()), \
                mock.patch.object(web, "get_provider", lambda c: provider), \
                mock.patch.object(web, "resolved_model_for", lambda p, m: "m"), \
                mock.patch.object(web, "default_effort_for", lambda p: "high"), \
                mock.patch.object(web, "guard_lock", mock.MagicMock()), \
                mock.patch.object(web, "kill_session_and_parent", kill), \
                mock.patch.object(web, "detect_display", lambda: ":0"), \
                mock.patch.object(web, "diag_log", lambda *a, **k: None), \
                mock.patch.object(web, "spawn_session", spawn):
            res = web._adopt("foo")
        self.assertFalse(res["ok"])
        kill.assert_not_called()
        self.assertTrue(spawn.call_args.kwargs.get("dry_run"))


if __name__ == "__main__":
    unittest.main()


class AdoptCliOptsValidation(unittest.TestCase):
    """review R-1: /api/adopt cli_opts doğrulaması (validate_cli_opts) eski oturum öldürülmeden yapılır."""

    def _run(self, provider, cli_opts):
        proc = SimpleNamespace(pid=1, name="foo", cwd="/tmp", cli="ucli", model="m")
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
            res = web._adopt("foo", cli_opts=cli_opts)
        return res, kill, spawn

    def test_invalid_opts_rejected_before_kill(self):
        provider = mock.Mock()
        provider.accepts_cli_opts = True
        provider.permission_modes.return_value = ["default"]
        provider.validate_cli_opts.return_value = ({}, "geçersiz seçenek")
        res, kill, spawn = self._run(provider, {"x": "../../evil"})
        self.assertFalse(res["ok"])
        self.assertIn("geçersiz", res["error"])
        kill.assert_not_called()
        spawn.assert_not_called()

    def test_provider_without_opts_support_rejected(self):
        provider = mock.Mock()
        provider.accepts_cli_opts = False
        provider.permission_modes.return_value = ["default"]
        res, kill, _ = self._run(provider, {"a": 1})
        self.assertFalse(res["ok"])
        kill.assert_not_called()

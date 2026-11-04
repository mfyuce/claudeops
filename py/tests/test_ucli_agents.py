"""ucli alt ajanları: kayıt defteri/token (`ucli_agents`) + sağlayıcı bayrak/env (`_agent_setup`). Gerçek Popen/ağ/tmux YOK;
tüm dosyalar geçici dizinde (gerçek ~/.claude/claudeops'a dokunmaz)."""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_agents as ag  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


class AgBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(ag, "STATE_FILE", os.path.join(self.tmp.name, "agents.json")),
                  mock.patch.object(ag, "TOKEN_DIR", os.path.join(self.tmp.name, "tokens")),
                  mock.patch.object(ag, "_PANEL_PORT", None)):
            p.start()
            self.addCleanup(p.stop)


class TokenTests(AgBase):
    def test_issue_writes_0600_file_and_only_hash_in_registry(self):
        path = ag.issue_token("p1")
        tok = open(path).read()
        self.assertEqual(len(tok), 64)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertNotIn(tok, open(ag.STATE_FILE).read())
        self.assertEqual(ag.parent_for_token(tok), "p1")

    def test_reissue_invalidates_old_token_and_revoke_clears(self):
        t1 = open(ag.issue_token("p1")).read()
        t2 = open(ag.issue_token("p1")).read()
        self.assertIsNone(ag.parent_for_token(t1))
        self.assertEqual(ag.parent_for_token(t2), "p1")
        ag.revoke_parent("p1")
        self.assertIsNone(ag.parent_for_token(t2))
        self.assertFalse(os.path.exists(ag.token_file("p1")))

    def test_children_get_no_token_and_garbage_rejected(self):
        with self.assertRaises(ValueError):
            ag.issue_token("p1_aj1")
        self.assertIsNone(ag.parent_for_token(""))
        self.assertIsNone(ag.parent_for_token("x" * 500))

    def test_revoke_unsafe_name_does_not_touch_files(self):
        victim = os.path.join(self.tmp.name, "victim")
        open(victim, "w").write("x")
        os.makedirs(ag.TOKEN_DIR)
        ag.revoke_parent("../victim")
        self.assertTrue(os.path.exists(victim))


class ReserveTests(AgBase):
    def test_limit_two_live_and_names_sequential(self):
        n1, _ = ag.reserve_child("p", set(), lambda n: False, {"cwd": "/x"})
        n2, _ = ag.reserve_child("p", {n1}, lambda n: False, {"cwd": "/x"})
        self.assertEqual((n1, n2), ("p_aj1", "p_aj2"))
        n3, why = ag.reserve_child("p", {n1, n2}, lambda n: False, {})
        self.assertIsNone(n3)
        self.assertIn("limit", why)
        ag.mark_stopped(n1)
        n4, _ = ag.reserve_child("p", {n2}, lambda n: False, {})
        self.assertEqual(n4, "p_aj3")          # sayaç geri sarmaz

    def test_taken_names_skipped_and_depth_one(self):
        n, _ = ag.reserve_child("p", set(), lambda name: name == "p_aj1", {})
        self.assertEqual(n, "p_aj2")
        n, why = ag.reserve_child("p_aj1", set(), lambda name: False, {})
        self.assertIsNone(n)

    def test_fold_text(self):
        self.assertEqual(ag.fold_text("a\n\n b \r\nc"), "a b c")
        self.assertTrue(ag.fold_text("/exit").startswith("Message: "))
        self.assertEqual(len(ag.fold_text("x" * 99999)), ag.MAX_TEXT_CHARS)


class SettingsTests(unittest.TestCase):
    def _with(self, **kw):
        from claudeops import settings
        return mock.patch.object(ag, "load_settings", lambda: {**settings.DEFAULT_SETTINGS, **kw})

    def test_defaults(self):
        with self._with():
            self.assertTrue(ag.enabled())
            self.assertEqual(ag.max_cost_usd(), 2.0)

    def test_off_and_cost(self):
        with self._with(ucli_agents="off", ucli_agents_max_cost_usd="3,5"):
            self.assertFalse(ag.enabled())
            self.assertEqual(ag.max_cost_usd(), 3.5)
        with self._with(ucli_agents_max_cost_usd="abc"):
            self.assertEqual(ag.max_cost_usd(), 2.0)
        with self._with(ucli_agents_max_cost_usd="0"):
            self.assertEqual(ag.max_cost_usd(), 0.0)


class ProviderSetupTests(AgBase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(up, "binary_supports_flag", lambda b, f: f == "--allow-agents")
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch.object(ag, "enabled", lambda: True)
        p2.start()
        self.addCleanup(p2.stop)
        p3 = mock.patch.object(up, "diag_log", lambda *a, **k: None)
        p3.start()
        self.addCleanup(p3.stop)

    def test_no_port_or_child_or_off_gives_nothing(self):
        self.assertEqual(up._agent_setup("ucli", "p"), ([], []))           # port bilinmiyor
        ag.set_panel_port(8765)
        self.addCleanup(ag.set_panel_port, None)
        self.assertEqual(up._agent_setup("ucli", "p_aj1"), ([], []))
        with mock.patch.object(up.ucli_agents, "enabled", lambda: False):
            self.assertEqual(up._agent_setup("ucli", "p"), ([], []))
        self.assertFalse(os.path.exists(ag.TOKEN_DIR))

    def test_unsupported_binary_gives_nothing(self):
        ag.set_panel_port(8765)
        self.addCleanup(ag.set_panel_port, None)
        with mock.patch.object(up, "binary_supports_flag", lambda b, f: False):
            self.assertEqual(up._agent_setup("ucli", "p"), ([], []))

    def test_enabled_returns_flag_and_env_without_token_value(self):
        ag.set_panel_port(8765)
        self.addCleanup(ag.set_panel_port, None)
        args, env = up._agent_setup("ucli", "p")
        self.assertEqual(args, ["--allow-agents"])
        self.assertIn("UCLI_AGENT_URL=http://127.0.0.1:8765", env)
        tok = open(ag.token_file("p")).read()
        self.assertTrue(any(e.startswith("UCLI_AGENT_TOKEN=") and tok not in e for e in env))
        self.assertFalse(any(tok in e for e in args + env))

    def test_build_inner_command_keeps_token_out_of_argv(self):
        ag.set_panel_port(8765)
        self.addCleanup(ag.set_panel_port, None)
        with mock.patch.object(up, "resolve_binary", lambda: "/bin/ucli"), \
                mock.patch.object(up, "_sync_api_key_file", lambda: False), \
                mock.patch.object(up, "_web_args", lambda *a: []), \
                mock.patch.object(up, "ucli_limit_overrides", lambda: {}), \
                mock.patch.object(up, "binary_derives_context", lambda b: True):
            cmd = up.UcliProvider().build_inner_command("/tmp", "m", "read-only", "medium", None, "", "p")
            child = up.UcliProvider().build_inner_command("/tmp", "m", "read-only", "medium", None, "", "p_aj1")
        tok = open(ag.token_file("p")).read()
        self.assertIn("--allow-agents", cmd)
        self.assertIn("UCLI_AGENT_TOKEN", cmd)
        self.assertNotIn(tok, cmd)
        self.assertNotIn("--allow-agents", child)
        self.assertNotIn("UCLI_AGENT_TOKEN", child)


if __name__ == "__main__":
    unittest.main()

"""TBD#412 (b): `CLAUDEOPS_DIR` başka dizindeyse ortak (`~/.claude/claudeops`) anahtar/kullanım dosyaları yalnız okunur."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import paths, ucli_client, ucli_compare, ucli_cost  # noqa: E402
from claudeops.providers import copilot_provider as cp  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


def _put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _read(path):
    with open(path) as f:
        return f.read()


class SharedStateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.join(tmp.name, "home")
        self.shared = os.path.join(self.home, ".claude", "claudeops")
        self.own = os.path.join(tmp.name, "own")
        os.makedirs(self.shared)
        os.makedirs(self.own)
        self.key = os.path.join(self.shared, "ucli_api_key")
        self.byok = os.path.join(self.shared, "copilot_byok_env")
        self.usage = os.path.join(self.shared, "ucli_usage")
        for p in (mock.patch.dict(os.environ, {"HOME": self.home}),
                  mock.patch.object(paths, "CLAUDEOPS_DIR", self.own),
                  mock.patch.object(up, "_API_KEY_FILE", self.key),
                  mock.patch.object(up, "_API_KEY_MANAGED_MARKER", self.key + ".managed"),
                  mock.patch.object(cp, "_BYOK_ENV_FILE", self.byok),
                  mock.patch.object(cp, "_BYOK_ENV_MANAGED_MARKER", self.byok + ".managed"),
                  mock.patch.object(ucli_cost, "USAGE_DIR", self.usage),
                  mock.patch.object(ucli_cost, "OTHER_DIR", os.path.join(self.usage, "other")),
                  mock.patch.object(ucli_client, "STATE_ROOT", os.path.join(self.shared, "ucli-state"))):
            p.start()
            self.addCleanup(p.stop)

    def _ucli(self, key):
        with mock.patch.object(up, "byok_env_for", lambda cli: {"UCLI_API_KEY": key} if key else {}):
            return up._sync_api_key_file()

    def _copilot(self, env):
        with mock.patch.object(cp, "byok_env_for", lambda cli: env):
            return cp._sync_byok_env_file()

    def test_allowed_only_outside_shared_or_default_instance(self):
        self.assertFalse(paths.shared_write_allowed(self.key))
        self.assertFalse(paths.shared_write_allowed(self.shared))
        self.assertTrue(paths.shared_write_allowed(os.path.join(self.own, "x")))
        link = os.path.join(self.own, "link")
        os.symlink(self.shared, link)
        self.assertFalse(paths.shared_write_allowed(os.path.join(link, "x")))   # bağ üzerinden de ortak
        with mock.patch.object(paths, "CLAUDEOPS_DIR", self.shared):
            self.assertTrue(paths.shared_write_allowed(self.key))

    def test_empty_setting_does_not_delete_shared_keys(self):
        for f in (self.key, self.byok):
            _put(f, "live")
            _put(f + ".managed", "")
        self.assertTrue(self._ucli(""))
        self.assertTrue(self._copilot({}))
        for f in (self.key, self.byok):
            self.assertEqual(_read(f), "live")
            self.assertTrue(os.path.exists(f + ".managed"))

    def test_other_setting_neither_written_nor_used(self):
        _put(self.key, "live")
        _put(self.byok, "export A=live\n")
        self.assertFalse(self._ucli("trial"))
        self.assertFalse(self._copilot({"A": "trial"}))
        self.assertEqual(_read(self.key), "live")
        self.assertEqual(_read(self.byok), "export A=live\n")

    def test_same_setting_is_used_and_missing_file_not_created(self):
        self.assertFalse(self._ucli("trial"))
        self.assertFalse(self._copilot({"A": "x"}))
        self.assertEqual(os.listdir(self.shared), [])
        _put(self.key, "live\n")
        _put(self.byok, "export A=live\n")
        self.assertTrue(self._ucli("live"))
        self.assertTrue(self._copilot({"A": "live"}))

    def _service(self, service, env, key):
        """`_apply_cli_opts`: (argv, anahtar env öneki)."""
        with mock.patch.object(up, "byok_env_for", lambda cli: {env: key} if key else {}), \
                mock.patch.object(up, "binary_supports_flag", lambda binary, flag: flag == "--provider"), \
                mock.patch.object(up, "diag_log", lambda *a, **k: None):
            return up._apply_cli_opts(["ucli", "chat", "--endpoint", "x"], {"service": service}, "s", self.own, "high")

    def test_service_key_of_a_second_instance_lives_in_its_own_dir(self):
        for service, env in (("grok", "XAI_API_KEY"), ("claude", "ANTHROPIC_API_KEY")):
            shared = os.path.join(self.shared, f"ucli_key_{service}")
            own = os.path.join(self.own, f"ucli_key_{service}")
            _put(shared, "live")
            before = os.stat(shared).st_mtime_ns
            with mock.patch.object(up, "_claude_service_flags", lambda argv, *a: argv):
                _, prefix = self._service(service, env, "trial")
            self.assertEqual(prefix, f'{env}="$(cat {own})"')
            self.assertEqual((_read(own), os.stat(own).st_mode & 0o777), ("trial", 0o600))
            self.assertEqual((_read(shared), os.stat(shared).st_mtime_ns), ("live", before))

    def test_second_instance_without_a_service_key_refuses_and_removes_only_its_own_key(self):
        shared = os.path.join(self.shared, "ucli_key_grok")
        own = os.path.join(self.own, "ucli_key_grok")
        _put(shared, "live")
        _put(shared + ".managed", "")
        _put(own, "eski")
        with self.assertRaises(ValueError):          # ortak anahtara düşülmez
            self._service("grok", "XAI_API_KEY", "")
        # TBD#451 (a): kaldırılan anahtarın bu örnekteki dosyası silinir; ortak dosyaya ve işaretine dokunulmaz
        self.assertEqual((_read(shared), os.path.lexists(own)), ("live", False))
        self.assertTrue(os.path.exists(shared + ".managed"))

    def test_preview_writes_no_service_key_but_names_the_own_path(self):
        own = os.path.join(self.own, "ucli_key_grok")
        with up.preview.preview_only():
            _, prefix = self._service("grok", "XAI_API_KEY", "trial")
        self.assertEqual(prefix, f'XAI_API_KEY="$(cat {own})"')
        self.assertEqual((os.listdir(self.shared), os.path.exists(own)), ([], False))

    def test_own_key_link_into_the_shared_dir_is_not_followed(self):
        shared = os.path.join(self.shared, "ucli_key_grok")
        _put(shared, "live")
        os.symlink(shared, os.path.join(self.own, "ucli_key_grok"))
        with self.assertRaises(OSError):
            self._service("grok", "XAI_API_KEY", "trial")
        self.assertEqual(_read(shared), "live")

    def test_default_instance_writes_the_shared_service_key(self):
        shared = os.path.join(self.shared, "ucli_key_grok")
        with mock.patch.object(paths, "CLAUDEOPS_DIR", self.shared):
            _, prefix = self._service("grok", "XAI_API_KEY", "canli")
        self.assertEqual(prefix, f'XAI_API_KEY="$(cat {shared})"')
        self.assertEqual(_read(shared), "canli")

    def test_usage_written_to_own_dir_and_both_counted(self):
        self.assertEqual(ucli_cost.log_path("s"), os.path.join(self.own, "ucli_usage", "s.jsonl"))
        self.assertEqual(ucli_cost.other_log_path("s"), os.path.join(self.own, "ucli_usage", "other", "s.jsonl"))
        _put(os.path.join(self.usage, "s.jsonl"), "{}\n")
        _put(ucli_cost.log_path("s"), "{}\n")
        base = ucli_cost.USAGE_DIR
        with mock.patch.object(ucli_cost.rv, "usage_cost_usd", lambda *a, **k: 2.0):
            self.assertEqual(ucli_cost.per_session_usd(base=base), {"s": 4.0})
            self.assertEqual(ucli_cost.total_usd(base=base), 4.0)
            self.assertEqual(ucli_cost.rate_usd_per_hour(base=base), 4.0)
        rows = ucli_compare._rows(base, "other", os.path.join(self.own, "m.db"), 0.0, 1.0)
        self.assertEqual([r["session"] for r in rows], ["s", "s"])
        self.assertEqual(os.listdir(self.usage), ["s.jsonl"])

    def test_unreadable_own_ledger_is_a_problem_in_a_second_instance(self):
        base = ucli_cost.USAGE_DIR
        _put(os.path.join(self.usage, "s.jsonl"), "{}\n")
        now = os.path.getmtime(os.path.join(self.usage, "s.jsonl"))
        self.assertEqual(ucli_cost._ledger_problem(now, base, 1.0), "")      # kendi dizini henüz yok: sorun değil
        own = ucli_cost.log_path("kendi")
        _put(own, '{"t": %d, "usage": {"input_tokens": -1}}\n' % int(now * 1000))
        self.assertEqual(ucli_cost._ledger_problem(now, base, 1.0), "kendi.jsonl: geçersiz sayaç")
        os.remove(own)
        os.rmdir(os.path.dirname(own))
        _put(os.path.dirname(own), "")                                      # dizin yerine dosya: listelenemez
        self.assertEqual(ucli_cost._ledger_problem(now, base, 1.0), "günlük dizini okunamadı")

    def test_default_instance_uses_shared_usage(self):
        with mock.patch.object(paths, "CLAUDEOPS_DIR", self.shared):
            self.assertEqual(ucli_cost.log_path("s"), os.path.join(self.usage, "s.jsonl"))
            self.assertEqual(ucli_cost.read_dirs(self.usage), [self.usage])

    def test_state_dir_own_and_shared_read_last(self):
        cwd = os.path.join(self.own, "proj")
        new = ucli_client.state_dir_for(cwd)
        self.assertEqual(os.path.dirname(new), os.path.join(self.own, "ucli-state"))
        old = os.path.join(self.shared, "ucli-state", os.path.basename(new))
        os.makedirs(old)
        self.assertEqual(ucli_client.chat_session_dirs(cwd)[-1], old)


if __name__ == "__main__":
    unittest.main()

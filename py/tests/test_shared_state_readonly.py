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

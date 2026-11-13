"""orch_store: eksik/geçersiz run id ValueError verir (KeyError değil); NUL/traversal reddedilir (review cliops|uzops 2 Kas)."""
import unittest

from claudeops import orch_store


class Ids(unittest.TestCase):
    def test_save_run_bad_ids(self):
        for bad in ({}, {"id": None}, {"id": 5}, {"id": ""}, {"id": "../x"}, {"id": "a\0b"}):
            with self.assertRaises(ValueError):
                orch_store.save_run(bad)

    def test_paths(self):
        self.assertIsNone(orch_store._run_path("a\0b"))
        self.assertIsNone(orch_store.load_run("../x"))
        with self.assertRaises(ValueError):
            orch_store.run_dir("../x")


if __name__ == "__main__":
    unittest.main()


class StartRunCleanup(unittest.TestCase):
    def test_setup_exception_releases_active_run(self):
        from unittest import mock
        from claudeops.commands import web_orch
        with mock.patch.object(web_orch, "_preflight", lambda p: None), \
                mock.patch.object(web_orch, "_eligible_index", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                web_orch.start_run([], "görev")
        self.assertIsNone(web_orch._ACTIVE_RUN_ID)
        self.assertEqual(web_orch._CANCEL_EVENTS, {})

    def test_write_private_stale_tmp_does_not_block(self):
        import os, tempfile
        from claudeops.commands import web_orch
        d = tempfile.mkdtemp()
        p = os.path.join(d, "task.md")
        open(f"{p}.{os.getpid()}.tmp", "w").write("eski")
        web_orch._write_private(p, "yeni")
        self.assertEqual(open(p).read(), "yeni")
        self.assertEqual(oct(os.stat(p).st_mode & 0o777), "0o600")

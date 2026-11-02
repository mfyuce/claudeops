"""`web._ucli_flags` (ucli satır rozetleri için cmdline özeti) — stdlib unittest, süreç taklit edilir.

Çalıştırma:  python3 py/tests/test_web_ucli_flags.py -v
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402


def _s(cli="ucli", pid=424242):
    return SimpleNamespace(cli=cli, pid=pid)


class UcliFlagsTest(unittest.TestCase):
    def setUp(self):
        web._UCLI_FLAGS_CACHE.clear()

    def _run(self, cmd, s=None):
        proc = mock.Mock()
        proc.cmdline.return_value = cmd
        with mock.patch.object(web.psutil, "Process", return_value=proc):
            return web._ucli_flags(s or _s())

    def test_non_ucli_and_none(self):
        self.assertIsNone(web._ucli_flags(None))
        self.assertIsNone(web._ucli_flags(_s(cli="claude")))

    def test_all_flags(self):
        out = self._run(["ucli", "chat", "--allow-edit", "--allow-exec-rust", "--max-cost-usd", "1.5"])
        self.assertEqual(out, {"write": True, "exec": True, "max_cost_usd": 1.5})

    def test_no_flags(self):
        out = self._run(["ucli", "chat", "--session", "x"])
        self.assertEqual(out, {"write": False, "exec": False, "max_cost_usd": None})

    def test_bad_cost_value(self):
        out = self._run(["ucli", "--max-cost-usd", "abc"])
        self.assertIsNone(out["max_cost_usd"])

    def test_process_error_returns_none_and_not_cached(self):
        with mock.patch.object(web.psutil, "Process", side_effect=RuntimeError("gone")):
            self.assertIsNone(web._ucli_flags(_s()))
        self.assertNotIn(424242, web._UCLI_FLAGS_CACHE)

    def test_cached_per_pid(self):
        self._run(["ucli", "--allow-edit"])
        with mock.patch.object(web.psutil, "Process", side_effect=AssertionError("must not re-read")):
            self.assertTrue(web._ucli_flags(_s())["write"])


if __name__ == "__main__":
    unittest.main()

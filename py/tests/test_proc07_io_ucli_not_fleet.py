"""PROC-07: `--repl`siz ucli (io_providers / reviewer) filo kesfine girmez; `_io_ask` canli ayni adli oturuma yazmaz."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.providers.ucli_provider import UcliProvider  # noqa: E402
from claudeops.commands import web  # noqa: E402


class MatchesProcTest(unittest.TestCase):
    def test_repl_is_fleet(self):
        self.assertTrue(UcliProvider().matches_proc(["/x/ucli", "--root", "/r", "chat", "--repl", "--session", "s"]))

    def test_oneshot_and_reviewer_are_not_fleet(self):
        p = UcliProvider()
        self.assertFalse(p.matches_proc(["/x/ucli", "--root", "/r", "chat", "--session", "s", "soru"]))
        self.assertFalse(p.matches_proc(["/x/ucli", "--root", "/r", "chat", "--model", "m", "incele"]))


class IoAskLiveNameTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_rejects_live_same_name(self):
        prov = mock.Mock()
        with mock.patch.object(web, "get_io_provider", lambda n: prov), \
                mock.patch.object(web, "find_sessions", lambda measure_cpu=False: [SimpleNamespace(cli="ucli", name="s1")]):
            res = web._io_ask("ucli", self.d, "s1", "merhaba", {})
        self.assertFalse(res["ok"])
        prov.ask.assert_not_called()

    def test_other_name_goes_through(self):
        prov = mock.Mock()
        prov.ask.return_value = {"answer": "x"}
        with mock.patch.object(web, "get_io_provider", lambda n: prov), \
                mock.patch.object(web, "find_sessions", lambda measure_cpu=False: [SimpleNamespace(cli="ucli", name="s1")]):
            res = web._io_ask("ucli", self.d, "s2", "merhaba", {})
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()

"""TBD#56: `_files_resolve` tam ad önce, tekil base yedek, 2+ adayda belirsiz hata (ilkini sessizce seçmez).

Çalıştırma:  python3 py/tests/test_files_resolve_exact_first.py -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web  # noqa: E402
from claudeops.session import Session  # noqa: E402


class FilesResolveTests(unittest.TestCase):
    def _run(self, live, name):
        with mock.patch.object(web, "find_sessions", lambda measure_cpu=False, **kw: list(live)), \
                mock.patch.object(web.inst_mod, "get_instance", lambda n: None), \
                mock.patch.object(web, "_fleet_status", lambda: {}):
            return web._files_resolve(name, "en")

    def test_exact_wins_over_base_siblings(self):
        live = [Session(name="cops", pid=1, cwd="/a", cli="claude"),
                Session(name="cops20261021_1", pid=2, cwd="/b", cli="claude")]
        s, err = self._run(live, "cops")
        self.assertIsNone(err)
        self.assertEqual(s.cwd, "/a")

    def test_single_base_fallback(self):
        live = [Session(name="cops20261021_1", pid=2, cwd="/b", cli="claude")]
        s, err = self._run(live, "cops")
        self.assertIsNone(err)
        self.assertEqual(s.pid, 2)

    def test_two_base_candidates_is_ambiguous(self):
        live = [Session(name="cops20261021_1", pid=2, cwd="/b", cli="claude"),
                Session(name="cops20261021_2", pid=3, cwd="/c", cli="claude")]
        s, err = self._run(live, "cops")
        self.assertIsNone(s)
        self.assertFalse(err["ok"])
        self.assertEqual(web._files_resolve_status(err), 409)

    def test_unknown_is_not_running(self):
        s, err = self._run([], "yok")
        self.assertIsNone(s)
        self.assertFalse(err["ok"])
        self.assertEqual(web._files_resolve_status(err), 404)

    def test_mutation_wrappers_return_409_when_ambiguous(self):
        live = [Session(name="cops20261021_1", pid=2, cwd="/b", cli="claude"),
                Session(name="cops20261021_2", pid=3, cwd="/c", cli="claude")]
        with mock.patch.object(web, "find_sessions", lambda measure_cpu=False, **kw: list(live)), \
                mock.patch.object(web.inst_mod, "get_instance", lambda n: None), \
                mock.patch.object(web, "_fleet_status", lambda: {}):
            for res in (web._files_delete("cops", "/x", "en"), web._files_mkdir("cops", None, "d", "en"),
                        web._files_write("cops", "/x", "t", "en"), web._files_rename("cops", "/x", "y", "en")):
                self.assertEqual(res[1], 409)


if __name__ == "__main__":
    unittest.main()

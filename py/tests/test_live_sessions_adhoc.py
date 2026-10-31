"""`_live_sessions`: kayıtsız (ad hoc) proje adı tarihli/_N'li çalışan oturuma çözülür (2026-10-31: `mecdtfl` direktifi
`mecdtfl20261031_1`i görmeyip --resume ile ikinci oturum açmıştı)."""
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from claudeops.commands import web_steward as ws  # noqa: E402


def _s(name):
    return NS(name=name, cwd="/x", sid="s")


class TestLiveSessionsAdHoc(unittest.TestCase):
    def _patched(self, scan, inst):
        return (mock.patch.object(ws, "_scan", lambda: scan), mock.patch.object(ws.sw, "load_projects", lambda sid="default": {}),
                mock.patch.object(ws, "_world", lambda sid="default", cfg=None: None),
                mock.patch.object(ws.inst_mod, "get_instance", lambda n: inst.get(n)))

    def test_unregistered_project_name_resolves_dated_session(self):
        scan = [_s("mecdtfl20261031_1"), _s("cli")]
        inst = {"mecdtfl20261031_1": {"blueprint": "mecdtfl"}}
        ps = self._patched(scan, inst)
        with ps[0], ps[1], ps[2], ps[3]:
            self.assertEqual([x.name for x in ws._live_sessions("mecdtfl")], ["mecdtfl20261031_1"])

    def test_exact_name_wins_and_other_projects_untouched(self):
        scan = [_s("mecdtfl20261031_1"), _s("mecdtfl")]
        ps = self._patched(scan, {"mecdtfl20261031_1": {"blueprint": "mecdtfl"}})
        with ps[0], ps[1], ps[2], ps[3]:
            self.assertEqual([x.name for x in ws._live_sessions("mecdtfl")], ["mecdtfl"])   # tam ad eşleşir
            self.assertEqual(ws._live_sessions("baska"), [])

    def test_two_dated_sessions_are_both_returned_for_ambiguity(self):
        scan = [_s("oiso20261017"), _s("oiso20261031")]
        ps = self._patched(scan, {})
        with ps[0], ps[1], ps[2], ps[3]:
            self.assertEqual(sorted(x.name for x in ws._live_sessions("oiso")), ["oiso20261017", "oiso20261031"])


if __name__ == "__main__":
    unittest.main()

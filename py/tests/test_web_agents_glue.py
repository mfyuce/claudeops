"""web.py yapıştırıcısı: `_agents_caller` (ajan token'ı yalnız /api/agents için), HOST_ROUTED_PATHS dışı, `_stop` kancası.
Gerçek sunucu/ağ/spawn YOK."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import ucli_agents as ag  # noqa: E402
from claudeops.commands import web, web_hosts  # noqa: E402


class CallerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(ag, "STATE_FILE", os.path.join(tmp.name, "a.json")),
                  mock.patch.object(ag, "TOKEN_DIR", os.path.join(tmp.name, "t"))):
            p.start()
            self.addCleanup(p.stop)
        self.tok = open(ag.issue_token("p")).read()

    def caller(self, panel_ok=False, bearer=None):
        h = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        fake = NS(_authorized=lambda: panel_ok, headers=h)
        return web._Handler._agents_caller(fake)

    def test_agent_token_maps_to_parent(self):
        self.assertEqual(self.caller(bearer=self.tok), ("agent", "p"))

    def test_panel_token_is_human(self):
        self.assertEqual(self.caller(panel_ok=True), ("human", ""))

    def test_bad_or_missing_token_rejected(self):
        self.assertIsNone(self.caller(bearer="0" * 64))
        self.assertIsNone(self.caller())

    def test_agent_token_is_not_a_panel_token(self):
        """`_authorized()` ajan token'ını TANIMAZ: başka hiçbir uç ona açılmaz."""
        fake = NS(path="/api/status", headers={"Authorization": f"Bearer {self.tok}"}, token="panel-secret")
        self.assertFalse(web._Handler._authorized(fake))

    def test_agents_paths_are_local_only(self):
        for p in ("/api/agents/start", "/api/agents/send", "/api/agents/stop"):
            self.assertNotIn(p, web_hosts.HOST_ROUTED_PATHS)


class StopHookTests(unittest.TestCase):
    def test_stop_notifies_agents_for_each_killed_session(self):
        s = NS(pid=1, name="p")
        with mock.patch.object(web, "_find_running_for_action", lambda name: ("exact", [s])), \
                mock.patch.object(web, "kill_session_and_parent", lambda *a, **k: "ok"), \
                mock.patch.object(web, "guard_lock", mock.MagicMock()), \
                mock.patch.object(web, "diag_log", lambda *a, **k: None), \
                mock.patch.object(web.web_agents, "parent_closed") as pc:
            res = web._stop("p")
        self.assertTrue(res["ok"])
        pc.assert_called_once_with("p", web._AGENT_OPS)


if __name__ == "__main__":
    unittest.main()

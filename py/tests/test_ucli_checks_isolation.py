"""run_checks C2 kalanı: kontrol kaydı dizini (CLAUDEOPS_DIR/ucli_checks) proje kökünün DIŞINDA kalır; /api/files/write
(files.write_text) oraya yazamaz; ajan Bearer token'ı yalnız /api/agents/* yollarında tanınır."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops import files as files_mod  # noqa: E402
from claudeops import ucli_checks as uck  # noqa: E402
from claudeops.session import Session  # noqa: E402


class FilesWriteCannotReachChecks(unittest.TestCase):
    def test_write_text_forbidden_outside_project_root(self):
        with tempfile.TemporaryDirectory() as td:
            proj = os.path.join(td, "proj"); ck = os.path.join(td, "ucli_checks")
            os.makedirs(proj); os.makedirs(ck)
            target = os.path.join(ck, "owner.json")
            open(target, "w").write("{}")
            os.symlink(target, os.path.join(proj, "link.json"))
            s = Session(name="x", pid=1, cwd=proj, cli="claude")
            for p in (target, os.path.join(proj, "..", "ucli_checks", "owner.json"), os.path.join(proj, "link.json")):
                r = files_mod.write_text(s, p, '{"x":1}')
                self.assertFalse(r.get("ok"), p)
            self.assertEqual(open(target).read(), "{}")

    def test_default_root_not_under_any_project(self):
        self.assertTrue(uck.ROOT.endswith("ucli_checks"))


class AgentTokenScope(unittest.TestCase):
    def test_agents_caller_only_for_agents_paths(self):
        import inspect
        from claudeops.commands import web
        src = inspect.getsource(web)
        self.assertIn('agents_caller = self._agents_caller() if path.startswith("/api/agents/") else None', src)
        self.assertIn('agent_call and path.startswith("/api/agents/")', src)


if __name__ == "__main__":
    unittest.main()

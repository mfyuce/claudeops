import unittest
from types import SimpleNamespace
from unittest import mock

from claudeops.commands import web_steward as ws


class RemoteOversizedResumeTests(unittest.TestCase):
    cfg = SimpleNamespace(resume_max_context_tokens=100000)

    def probe(self, caps, facts):
        return mock.patch.object(ws, "_probe_facts", return_value=({"api": 1, "capabilities": caps}, facts))

    def test_big_context_returns_tokens(self):
        with self.probe(["resume_context"], {"x": {"resume_context_tokens": 386000}}):
            self.assertEqual(ws._remote_oversized_resume("h", "x", self.cfg), 386000)

    def test_small_or_missing_is_zero(self):
        with self.probe(["resume_context"], {"x": {"resume_context_tokens": 5000}}):
            self.assertEqual(ws._remote_oversized_resume("h", "x", self.cfg), 0)
        with self.probe(["resume_context"], {"x": {"resume_context_tokens": None}}):
            self.assertEqual(ws._remote_oversized_resume("h", "x", self.cfg), 0)

    def test_old_host_without_capability_is_zero(self):
        with self.probe(["session_facts"], {"x": {"resume_context_tokens": 386000}}):
            self.assertEqual(ws._remote_oversized_resume("h", "x", self.cfg), 0)

    def test_threshold_off(self):
        with self.probe(["resume_context"], {"x": {"resume_context_tokens": 386000}}):
            self.assertEqual(ws._remote_oversized_resume("h", "x", SimpleNamespace(resume_max_context_tokens=0)), 0)

    def test_host_facts_for_stopped_name_carry_resume_tokens(self):
        from claudeops.commands import web
        with mock.patch.object(web, "find_sessions", return_value=[]), \
                mock.patch.object(web.web_steward, "resume_context_tokens", return_value=250000):
            out = web._session_facts(["gone"])
        self.assertEqual(out["sessions"]["gone"]["resume_context_tokens"], 250000)
        self.assertIn("resume_context", out["capabilities"])


if __name__ == "__main__":
    unittest.main()

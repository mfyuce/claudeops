import unittest
from claudeops.commands import web_agents
from claudeops.providers import ucli_provider as up


class EffortSingleSource(unittest.TestCase):
    def test_no_local_copy(self):
        self.assertFalse(hasattr(web_agents, "_DEFAULT_EFFORTS"))

    def test_fallback_follows_provider(self):
        self.assertEqual(web_agents._efforts_for("evren", "x"), list(up._EFFORT_LEVELS))

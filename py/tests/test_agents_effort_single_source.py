import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeops.commands import web_agents  # noqa: E402
from claudeops.providers import ucli_provider as up  # noqa: E402


class EffortSingleSource(unittest.TestCase):
    def test_no_local_copy(self):
        self.assertFalse(hasattr(web_agents, "_DEFAULT_EFFORTS"))

    def test_fallback_follows_provider(self):
        self.assertEqual(web_agents._efforts_for("evren", "x"), list(up._EFFORT_LEVELS))


class BusyRule(unittest.TestCase):
    def test_rule(self):
        self.assertFalse(up.busy_from_status({"activity": "waiting_for_stdin"}))
        for a in ("waiting_for_model", "running_tool", "waiting_for_user", None):
            self.assertTrue(up.busy_from_status({"activity": a}))
